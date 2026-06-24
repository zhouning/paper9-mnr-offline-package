# -*- coding: utf-8 -*-
"""
Block Definition: aggregate parcels into candidate consolidation blocks.

Uses DLTB barrier features (roads, water, construction land) to segment
farmland+forest parcels into spatially contiguous candidate blocks.

Usage (CLI):
    python block_definition.py                       # all townships
    python block_definition.py --township <code>     # single township
    python block_definition.py --township <code> --visualize

When invoked from Tool 1 (PrepareDataTool), DLTB_PATH / OUTPUT_DIR /
TOWNSHIPS are monkey-patched at runtime so the values below are
placeholders for standalone CLI testing only.
"""

import os
import sys
import json
import argparse
import numpy as np
import geopandas as gpd
from scipy.sparse import lil_matrix
from sklearn.cluster import AgglomerativeClustering
from shapely.ops import unary_union
import warnings
warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Placeholders. Tool 1 patches these at runtime to point at the
# user's prepared_dir.
DLTB_PATH = os.path.join(SCRIPT_DIR, 'dem_slope_analysis', 'output', 'DLTB_with_slope.gpkg')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'results_real', 'blocks')
PROJ_CRS = 'EPSG:32648'  # UTM Zone 48N (override for other regions)

TOWNSHIPS = {}  # caller fills in {code: label}

# DLBM code prefixes
FARMLAND_PREFIXES = ('011', '012', '013')  # paddy, irrigated, dry land
FOREST_PREFIXES = ('031', '032', '033')    # forest, shrub, other woodland
BARRIER_PREFIXES = ('10', '11', '20')       # roads, water, construction


def classify_parcel(dlbm):
    """Classify parcel as farmland, forest, barrier, or other."""
    if dlbm.startswith(FARMLAND_PREFIXES):
        return 'farmland'
    elif dlbm.startswith(FOREST_PREFIXES):
        return 'forest'
    elif dlbm[:2] in ('10', '11', '20'):
        return 'barrier'
    else:
        return 'other'


def load_township(township_code):
    """Load all parcels for a township."""
    gdf = gpd.read_file(DLTB_PATH, where=f"QSDWDM LIKE '{township_code}%'")
    gdf['category'] = gdf['DLBM'].apply(classify_parcel)
    return gdf


def build_swappable_adjacency(gdf_swappable):
    """Build Queen contiguity adjacency for swappable parcels only.

    Two swappable parcels are adjacent if they share a boundary segment
    (not just touch at a point through a barrier).
    """
    try:
        from libpysal.weights import Queen
        w = Queen.from_dataframe(gdf_swappable, use_index=False)
        return w
    except Exception as e:
        print(f"  libpysal Queen failed: {e}, falling back to spatial index")
        # Fallback: use tiny buffer intersection
        from shapely.strtree import STRtree
        geoms = gdf_swappable.geometry.values
        tree = STRtree(geoms)
        adj = {i: set() for i in range(len(geoms))}
        for i, geom in enumerate(geoms):
            candidates = tree.query(geom, predicate='intersects')
            for j in candidates:
                if i != j and geoms[i].touches(geoms[j]) or geoms[i].intersects(geoms[j]):
                    adj[i].add(j)
                    adj[j].add(i)
        return adj


def find_connected_components(adjacency, n_parcels):
    """Find connected components using BFS."""
    visited = set()
    components = []

    # Handle libpysal Weights object or dict
    if hasattr(adjacency, 'neighbors'):
        get_neighbors = lambda i: adjacency.neighbors[i]
    else:
        get_neighbors = lambda i: adjacency.get(i, set())

    for start in range(n_parcels):
        if start in visited:
            continue
        # BFS
        component = []
        queue = [start]
        visited.add(start)
        while queue:
            node = queue.pop(0)
            component.append(node)
            for neighbor in get_neighbors(node):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        components.append(component)

    return components


def build_connectivity_matrix(adjacency, indices):
    """Build a sparse connectivity matrix for a subset of parcels.

    Args:
        adjacency: libpysal Weights object or dict
        indices: list of parcel indices (in the original gdf)

    Returns:
        scipy sparse CSR matrix of shape (len(indices), len(indices))
    """
    idx_map = {orig: new for new, orig in enumerate(indices)}
    n = len(indices)
    mat = lil_matrix((n, n), dtype=np.int8)

    if hasattr(adjacency, 'neighbors'):
        get_neighbors = lambda i: adjacency.neighbors[i]
    else:
        get_neighbors = lambda i: adjacency.get(i, set())

    for orig_idx in indices:
        new_i = idx_map[orig_idx]
        for neighbor in get_neighbors(orig_idx):
            if neighbor in idx_map:
                new_j = idx_map[neighbor]
                mat[new_i, new_j] = 1
                mat[new_j, new_i] = 1

    return mat.tocsr()


def subdivide_large_components(components, adjacency, gdf_proj, max_parcels=30):
    """Subdivide large connected components using spatially constrained clustering.

    Uses AgglomerativeClustering with connectivity constraint so that
    resulting sub-blocks are spatially contiguous.

    Args:
        components: list of lists of parcel indices
        adjacency: libpysal Weights or dict adjacency
        gdf_proj: GeoDataFrame in projected CRS (for centroid features)
        max_parcels: maximum parcels per block (components larger than this get split)

    Returns:
        subdivided: list of lists of parcel indices (each list = one block)
    """
    subdivided = []

    for comp in components:
        if len(comp) <= max_parcels:
            subdivided.append(comp)
            continue

        # Number of sub-blocks: target ~15-25 parcels each
        target_size = 20
        n_clusters = max(2, len(comp) // target_size)

        # Build connectivity matrix for this component
        conn = build_connectivity_matrix(adjacency, comp)

        # Feature matrix: centroid coordinates (projected) for spatial clustering
        centroids = gdf_proj.iloc[comp].geometry.centroid
        X = np.column_stack([centroids.x.values, centroids.y.values])

        try:
            clustering = AgglomerativeClustering(
                n_clusters=n_clusters,
                connectivity=conn,
                linkage='ward',
            )
            labels = clustering.fit_predict(X)

            # Group parcels by cluster label
            for label in range(n_clusters):
                mask = labels == label
                sub_block = [comp[i] for i in range(len(comp)) if mask[i]]
                if len(sub_block) > 0:
                    subdivided.append(sub_block)
        except Exception as e:
            print(f"    Warning: clustering failed for component of {len(comp)} parcels: {e}")
            subdivided.append(comp)

    return subdivided


def compute_block_features(gdf_proj, block_parcels, block_id):
    """Compute features for a single block."""
    parcels = gdf_proj.iloc[block_parcels]

    farm_mask = parcels['category'] == 'farmland'
    forest_mask = parcels['category'] == 'forest'

    farm_parcels = parcels[farm_mask]
    forest_parcels = parcels[forest_mask]

    total_area = parcels.geometry.area.sum()
    farm_area = farm_parcels.geometry.area.sum() if len(farm_parcels) > 0 else 0
    forest_area = forest_parcels.geometry.area.sum() if len(forest_parcels) > 0 else 0

    # Slope stats (area-weighted for farmland)
    if len(farm_parcels) > 0 and 'slope_mean' in farm_parcels.columns:
        farm_areas = farm_parcels.geometry.area.values
        farm_slopes = farm_parcels['slope_mean'].values
        avg_farm_slope = np.average(farm_slopes, weights=farm_areas)
    else:
        avg_farm_slope = 0.0

    if len(forest_parcels) > 0 and 'slope_mean' in forest_parcels.columns:
        forest_areas = forest_parcels.geometry.area.values
        forest_slopes = forest_parcels['slope_mean'].values
        avg_forest_slope = np.average(forest_slopes, weights=forest_areas)
    else:
        avg_forest_slope = 0.0

    # Block shape compactness (isoperimetric quotient)
    block_geom = unary_union(parcels.geometry.values)
    if block_geom.is_empty:
        compactness = 0.0
    else:
        perimeter = block_geom.length
        area = block_geom.area
        compactness = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0.0

    return {
        'block_id': block_id,
        'n_parcels': len(parcels),
        'n_farmland': int(farm_mask.sum()),
        'n_forest': int(forest_mask.sum()),
        'total_area_m2': float(total_area),
        'total_area_ha': float(total_area / 10000),
        'farm_area_ha': float(farm_area / 10000),
        'forest_area_ha': float(forest_area / 10000),
        'avg_farm_slope': float(avg_farm_slope),
        'avg_forest_slope': float(avg_forest_slope),
        'compactness': float(compactness),
    }


def define_blocks(township_code, min_parcels=3, min_area_ha=0.5, max_parcels=30):
    """Main block definition pipeline for a township.

    Args:
        township_code: Township QSDWDM prefix
        min_parcels: Minimum parcels per block (smaller blocks are merged or dropped)
        min_area_ha: Minimum block area in hectares
        max_parcels: Maximum parcels per block (larger components get subdivided)

    Returns:
        gdf_swappable: GeoDataFrame with block_id column added
        block_features: list of block feature dicts
    """
    print(f"\n{'='*60}")
    print(f"  Block Definition: {TOWNSHIPS.get(township_code, township_code)}")
    print(f"{'='*60}")

    # Step 1: Load and classify
    print("  Step 1: Loading parcels...")
    gdf = load_township(township_code)
    print(f"    Total: {len(gdf)} parcels")
    print(f"    Farmland: {(gdf['category']=='farmland').sum()}")
    print(f"    Forest: {(gdf['category']=='forest').sum()}")
    print(f"    Barriers: {(gdf['category']=='barrier').sum()}")
    print(f"    Other: {(gdf['category']=='other').sum()}")

    # Step 2: Extract swappable parcels
    gdf_swappable = gdf[gdf['category'].isin(['farmland', 'forest'])].copy()
    gdf_swappable = gdf_swappable.reset_index(drop=True)
    print(f"\n  Step 2: {len(gdf_swappable)} swappable parcels extracted")

    # Step 3: Build adjacency on swappable parcels only
    print("  Step 3: Building adjacency (Queen contiguity)...")
    adjacency = build_swappable_adjacency(gdf_swappable)

    # Step 4: Find connected components
    print("  Step 4: Finding connected components...")
    components = find_connected_components(adjacency, len(gdf_swappable))
    print(f"    Raw components: {len(components)}")

    # Project for area calculation
    gdf_proj = gdf_swappable.to_crs(PROJ_CRS)

    # Step 5: Subdivide large components
    print("  Step 5: Subdividing large components...")
    subdivided = subdivide_large_components(components, adjacency, gdf_proj, max_parcels=max_parcels)
    print(f"    After subdivision (max {max_parcels} parcels/block): {len(subdivided)} blocks")

    # Step 6: Filter by size
    valid_blocks = []
    dropped_parcels = []
    for comp in subdivided:
        area_ha = gdf_proj.iloc[comp].geometry.area.sum() / 10000
        if len(comp) >= min_parcels and area_ha >= min_area_ha:
            valid_blocks.append(comp)
        else:
            dropped_parcels.extend(comp)

    print(f"    After filtering (>={min_parcels} parcels, >={min_area_ha} ha): {len(valid_blocks)} blocks")
    print(f"    Dropped parcels (tiny fragments): {len(dropped_parcels)}")

    # Step 7: Assign block IDs
    gdf_swappable['block_id'] = -1
    for block_id, parcel_indices in enumerate(valid_blocks):
        for idx in parcel_indices:
            gdf_swappable.iloc[idx, gdf_swappable.columns.get_loc('block_id')] = block_id

    assigned = gdf_swappable[gdf_swappable['block_id'] >= 0]
    print(f"    Assigned parcels: {len(assigned)} / {len(gdf_swappable)}")

    # Step 8: Compute block features
    print("  Step 8: Computing block features...")
    block_features = []
    for block_id, parcel_indices in enumerate(valid_blocks):
        feat = compute_block_features(gdf_proj, parcel_indices, block_id)
        block_features.append(feat)

    # Summary statistics
    areas = [b['total_area_ha'] for b in block_features]
    n_parcels_list = [b['n_parcels'] for b in block_features]
    print(f"\n  === Block Summary ===")
    print(f"    Blocks: {len(block_features)}")
    print(f"    Parcels per block: min={min(n_parcels_list)}, median={np.median(n_parcels_list):.0f}, max={max(n_parcels_list)}")
    print(f"    Area (ha): min={min(areas):.2f}, median={np.median(areas):.2f}, max={max(areas):.2f}, total={sum(areas):.2f}")
    print(f"    Blocks >= 6.67 ha (百亩方): {sum(1 for a in areas if a >= 6.67)}")
    print(f"    Blocks >= 33.3 ha (500亩): {sum(1 for a in areas if a >= 33.3)}")

    return gdf_swappable, block_features, valid_blocks


def save_results(township_code, gdf_swappable, block_features, valid_blocks):
    """Save block definition results."""
    out_dir = os.path.join(OUTPUT_DIR, f'township_{township_code}')
    os.makedirs(out_dir, exist_ok=True)

    # Save parcel-to-block mapping
    mapping = gdf_swappable[['block_id']].copy()
    mapping['original_index'] = gdf_swappable.index
    mapping.to_csv(os.path.join(out_dir, 'parcel_block_mapping.csv'), index=False)

    # Save block features
    with open(os.path.join(out_dir, 'block_features.json'), 'w', encoding='utf-8') as f:
        json.dump(block_features, f, indent=2, ensure_ascii=False)

    # Save block compositions (which parcel indices belong to each block)
    block_compositions = {str(i): indices for i, indices in enumerate(valid_blocks)}
    with open(os.path.join(out_dir, 'block_compositions.json'), 'w') as f:
        json.dump(block_compositions, f)

    print(f"  Saved to {out_dir}")
    return out_dir


def visualize_blocks(township_code, gdf_swappable, block_features):
    """Generate block visualization map."""
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    out_dir = os.path.join(OUTPUT_DIR, f'township_{township_code}')

    assigned = gdf_swappable[gdf_swappable['block_id'] >= 0].copy()
    n_blocks = len(block_features)

    # Color by block_id
    fig, ax = plt.subplots(1, 1, figsize=(12, 10))

    # Plot unassigned in gray
    unassigned = gdf_swappable[gdf_swappable['block_id'] < 0]
    if len(unassigned) > 0:
        unassigned.plot(ax=ax, color='lightgray', edgecolor='gray', linewidth=0.2, alpha=0.5)

    # Plot blocks with distinct colors
    cmap = plt.cm.get_cmap('tab20', min(n_blocks, 20))
    assigned.plot(ax=ax, column='block_id', cmap='tab20', edgecolor='black',
                  linewidth=0.3, alpha=0.7, legend=False)

    ax.set_title(f'Block Definition: Township {TOWNSHIPS.get(township_code, township_code)}\n'
                 f'{n_blocks} blocks from {len(gdf_swappable)} swappable parcels',
                 fontsize=14)
    ax.set_axis_off()

    # Add stats text
    areas = [b['total_area_ha'] for b in block_features]
    baimu = sum(1 for a in areas if a >= 6.67)
    stats_text = (f'Blocks: {n_blocks}\n'
                  f'Median area: {np.median(areas):.1f} ha\n'
                  f'>=6.67 ha (百亩方): {baimu}')
    ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    fig_path = os.path.join(out_dir, 'block_map.png')
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved visualization: {fig_path}")


def main():
    parser = argparse.ArgumentParser(description='Define candidate consolidation blocks')
    parser.add_argument('--township', type=str, default=None, help='Township code (default: all)')
    parser.add_argument('--min-parcels', type=int, default=3, help='Min parcels per block')
    parser.add_argument('--min-area', type=float, default=0.5, help='Min block area (ha)')
    parser.add_argument('--max-parcels', type=int, default=30, help='Max parcels per block (larger blocks get subdivided)')
    parser.add_argument('--visualize', action='store_true', help='Generate block maps')
    args = parser.parse_args()

    townships = [args.township] if args.township else list(TOWNSHIPS.keys())

    for tc in townships:
        gdf_swap, block_feats, valid_blocks = define_blocks(
            tc, min_parcels=args.min_parcels, min_area_ha=args.min_area,
            max_parcels=args.max_parcels
        )
        out_dir = save_results(tc, gdf_swap, block_feats, valid_blocks)

        if args.visualize:
            visualize_blocks(tc, gdf_swap, block_feats)

    print("\nDone!")


if __name__ == '__main__':
    main()
