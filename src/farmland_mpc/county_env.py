# -*- coding: utf-8 -*-
"""
County-Level MDP Environment for farmland consolidation.

Scales the Block-Level MDP from a single township to a full county
(typically thousands of blocks across many townships). Cross-township
parcel adjacency enables baimu-fang formation across township
boundaries, creating coordination value that independent per-township
optimization cannot capture.

Compatible with sb3-contrib MaskablePPO + a per-block scoring policy.

Usage:
    env = CountyLevelEnv(total_budget=500, swaps_per_step=5)
    obs, info = env.reset()
    action = env.action_space.sample()
    obs, reward, done, truncated, info = env.step(action)

NOTE: ALL_TOWNSHIPS, DLTB_PATH and BLOCK_DIR are placeholders below.
The expected wiring path is via core.blocks_env.make_env(prepared_dir),
which reads townships.json + DLTB_with_slope.shp under prepared_dir
(the output of Tool 1) and monkey-patches these module globals before
instantiating CountyLevelEnv.
"""

import os
import json
import numpy as np
import geopandas as gpd
import gymnasium as gym
from gymnasium import spaces
from collections import deque

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Placeholders. blocks_env.make_env() patches these to point at the
# user's prepared_dir before instantiating CountyLevelEnv. They are
# populated here only so that bare imports do not fail.
DLTB_PATH = None
BLOCK_DIR = None
PROJ_CRS = 'EPSG:32648'

FARMLAND = 1
FOREST = 2

FARMLAND_PREFIXES = ('011', '012', '013')
FOREST_PREFIXES = ('031', '032', '033')

# Per-block feature count
K_BLOCK = 17
# County-level global feature count (9 base + 3 county-specific)
K_GLOBAL_COUNTY = 12

# Baimu-fang threshold: 100 mu = 6.67 hectares = 66,700 m2
BAIMU_THRESHOLD_M2 = 66700.0

# Township registry. Caller (blocks_env.make_env) overwrites this with
# the contents of prepared_dir/townships.json. Two synthetic entries
# below let the module import cleanly and serve as a schema example.
ALL_TOWNSHIPS = {
    'XXXXXX001': 'T01-Demo',
    'XXXXXX002': 'T02-Demo',
}

TOWNSHIP_CODES = sorted(ALL_TOWNSHIPS.keys())


def _classify_type(dlbm):
    if dlbm.startswith(FARMLAND_PREFIXES):
        return FARMLAND
    elif dlbm.startswith(FOREST_PREFIXES):
        return FOREST
    return 0


class CountyLevelEnv(gym.Env):
    """County-level land use optimization environment.

    Extends a single-township block environment to multiple townships.
    Agent selects which block (out of N) to invest in each step.
    Cross-township parcel adjacency enables baimu-fang formation
    across township boundaries.

    State:
        Per-block features (n_blocks x K_BLOCK) + county globals (K_GLOBAL_COUNTY).
    Action:
        Discrete(n_blocks) -- select which block to invest in.
    Episode:
        Fixed length = total_budget // swaps_per_step.
    """

    metadata = {"render_modes": []}

    def __init__(self, total_budget=500, swaps_per_step=5,
                 slope_weight=4000.0, cont_weight=500.0,
                 baimu_weight=1500.0, baimu_bonus=5.0,
                 baimu_area_penalty=2000.0,
                 cultivated_area_floor_delta_ha=None,
                 baimu_area_floor_delta_ha=None,
                 baimu_threshold_m2=BAIMU_THRESHOLD_M2,
                 gamma_conn=1.0, delta_conn=0.5):
        super().__init__()

        self.total_budget = total_budget
        self.swaps_per_step = swaps_per_step
        self.max_steps = total_budget // swaps_per_step
        self.slope_weight = slope_weight
        self.cont_weight = cont_weight
        self.baimu_weight = baimu_weight
        self.baimu_bonus = baimu_bonus
        self.baimu_area_penalty = baimu_area_penalty
        self.cultivated_area_floor_delta_ha = (
            None if cultivated_area_floor_delta_ha is None
            else float(cultivated_area_floor_delta_ha)
        )
        self.cultivated_area_floor_m2 = None
        self.baimu_area_floor_delta_ha = (
            None if baimu_area_floor_delta_ha is None
            else float(baimu_area_floor_delta_ha)
        )
        self.baimu_area_floor_m2 = None
        self.baimu_threshold_m2 = baimu_threshold_m2
        self.gamma_conn = gamma_conn
        self.delta_conn = delta_conn

        # Load all township data, build cross-township adjacency
        self._load_data()

        # Spaces
        self.n_blocks = len(self.block_parcels)
        self.n_townships = len(TOWNSHIP_CODES)
        self.action_space = spaces.Discrete(self.n_blocks)
        obs_dim = self.n_blocks * K_BLOCK + K_GLOBAL_COUNTY
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        # Initialize state
        self.land_use = self.initial_types.copy()
        self.swapped = np.zeros(self.n_parcels, dtype=bool)
        self.budget_used = 0
        self.step_count = 0
        self.swaps_in_block = np.zeros(self.n_blocks, dtype=np.int32)

        # Per-block available counters
        self._block_farm_avail = np.zeros(self.n_blocks, dtype=np.int32)
        self._block_forest_avail = np.zeros(self.n_blocks, dtype=np.int32)
        self._init_block_counters()

        # Compute initial metrics
        self._compute_metrics_full()
        self.baimu_count, self.baimu_total_area = self._count_baimu_fang()
        self._cache_initial_state()

        print(f"  Obs dim: {obs_dim}, Action dim: {self.n_blocks}")
        print(f"  Initial avg farmland slope: {self.avg_farmland_slope:.4f}")
        print(f"  Initial contiguity: {self.contiguity:.4f}")
        print(f"  Initial baimu fang: {self.baimu_count} patches, "
              f"{self.baimu_total_area/10000:.1f} ha total")
        print(f"  Block adjacency: median {np.median([len(a) for a in self.block_adj]):.0f} neighbors")
        print(f"  Cross-township block edges: {self.n_cross_township_edges}")

    # ==================================================================
    # Data loading (county-level)
    # ==================================================================

    def _load_data(self):
        """Load all 13 townships, build cross-township adjacency, merge blocks."""
        import time
        t0 = time.time()
        print("CountyLevelEnv: Loading parcels...")

        # Load all parcels matching the configured township codes
        where_clause = " OR ".join(
            [f"QSDWDM LIKE '{code}%'" for code in TOWNSHIP_CODES]
        )
        gdf = gpd.read_file(DLTB_PATH, where=where_clause)
        gdf['type_code'] = gdf['DLBM'].apply(_classify_type)

        # Filter to swappable (farmland + forest)
        gdf_swap = gdf[gdf['type_code'].isin([FARMLAND, FOREST])].copy()
        gdf_swap = gdf_swap.reset_index(drop=True)
        self.n_parcels = len(gdf_swap)

        # Project for area computation
        gdf_proj = gdf_swap.to_crs(PROJ_CRS)

        # Extract arrays
        self.initial_types = gdf_swap['type_code'].values.astype(np.int8)
        self.slopes = gdf_swap['slope_mean'].values.astype(np.float64)
        # Defense in depth: prepared dirs from older Tool 1 runs may carry
        # NaN slopes (DEM coverage gaps). Fill with median so slope_min/max
        # and downstream features stay finite. Trainer will fail with NaN
        # loss otherwise.
        slope_nan = np.isnan(self.slopes)
        n_nan = int(slope_nan.sum())
        if n_nan:
            finite = self.slopes[~slope_nan]
            if finite.size == 0:
                raise RuntimeError(
                    f"All {len(self.slopes)} parcel slopes are NaN in {DLTB_PATH}. "
                    "DEM probably did not cover the AOI; re-run Tool 1 with a "
                    "larger DEM extent."
                )
            fill = float(np.median(finite))
            self.slopes = np.where(slope_nan, fill, self.slopes)
            print(f"  WARN: {n_nan}/{len(self.slopes)} parcels had NaN slope_mean; "
                  f"filled with median={fill:.3f} deg")
        self.areas = gdf_proj.geometry.area.values.astype(np.float64)

        # Slope normalization params
        self.slope_min = float(self.slopes.min())
        self.slope_max = float(self.slopes.max())
        self.slope_range = self.slope_max - self.slope_min + 1e-8

        # Identify which township each parcel belongs to (6-digit prefix of QSDWDM)
        # QSDWDM is 12 digits; first 9 digits are township code
        qsdwdm = gdf_swap['QSDWDM'].values
        self.parcel_township = np.full(self.n_parcels, -1, dtype=np.int32)
        self._township_parcel_indices = {}  # code -> sorted array of global indices

        for ti, code in enumerate(TOWNSHIP_CODES):
            mask = np.array([str(q).startswith(code) for q in qsdwdm], dtype=bool)
            indices = np.where(mask)[0]
            self.parcel_township[indices] = ti
            self._township_parcel_indices[code] = indices

        n_assigned = int((self.parcel_township >= 0).sum())
        print(f"  {self.n_parcels} swappable parcels, {n_assigned} assigned to townships")
        t_load = time.time() - t0

        # Build adjacency (Queen contiguity across ALL parcels)
        t1 = time.time()
        print(f"  Building cross-township adjacency ({self.n_parcels} parcels)...")
        self._build_adjacency(gdf_swap)
        t_adj = time.time() - t1

        # Load and merge block compositions from all townships
        t2 = time.time()
        self._load_all_blocks()
        t_blocks = time.time() - t2

        # Build block adjacency (including cross-township edges)
        self._build_block_adjacency()

        # Pre-compute padded arrays for vectorized _get_block_features()
        self._precompute_padded_arrays()

        t_total = time.time() - t0
        print(f"  Load times: parcels={t_load:.1f}s, adjacency={t_adj:.1f}s, "
              f"blocks={t_blocks:.1f}s, total={t_total:.1f}s")
        print(f"  Budget: {self.total_budget} swaps, {self.swaps_per_step}/step, "
              f"{self.max_steps} steps")

    def _build_adjacency(self, gdf_swap):
        """Build adjacency lists via libpysal Queen contiguity (cross-township)."""
        try:
            from libpysal.weights import Queen
            w = Queen.from_dataframe(gdf_swap, use_index=False)
            self.adjacency = [np.array(w.neighbors[i], dtype=np.intp)
                              for i in range(self.n_parcels)]
        except Exception as e:
            print(f"  libpysal failed ({e}), using spatial index fallback")
            from shapely.strtree import STRtree
            geoms = gdf_swap.geometry.values
            tree = STRtree(geoms)
            self.adjacency = []
            for i in range(self.n_parcels):
                cands = tree.query(geoms[i], predicate='intersects')
                self.adjacency.append(np.array([j for j in cands if j != i], dtype=np.intp))

        self.total_nbr_count = np.array(
            [len(self.adjacency[i]) for i in range(self.n_parcels)], dtype=np.float32
        )

        # Count cross-township adjacencies
        cross_count = 0
        for i in range(self.n_parcels):
            ti = self.parcel_township[i]
            for j in self.adjacency[i]:
                if self.parcel_township[j] != ti:
                    cross_count += 1
        print(f"  Cross-township parcel adjacencies: {cross_count // 2} edges")

    def _load_all_blocks(self):
        """Load block compositions from all 13 townships and re-index to global parcels."""
        self.block_parcels = []
        self.block_to_township = []  # township index for each block

        for ti, code in enumerate(TOWNSHIP_CODES):
            block_dir = os.path.join(BLOCK_DIR, f'township_{code}')
            comp_path = os.path.join(block_dir, 'block_compositions.json')

            if not os.path.exists(comp_path):
                print(f"  WARNING: No blocks for {code}, skipping")
                continue

            with open(comp_path) as f:
                compositions = json.load(f)

            # Global indices for this township's swappable parcels
            global_indices = self._township_parcel_indices[code]

            n_blocks_this = len(compositions)
            for i in range(n_blocks_this):
                local_parcels = np.array(compositions[str(i)], dtype=np.intp)
                # Re-index: local index -> global index
                global_parcels = global_indices[local_parcels]
                self.block_parcels.append(global_parcels)
                self.block_to_township.append(ti)

        self.block_to_township = np.array(self.block_to_township, dtype=np.int32)

        # Block-level static attributes
        self.block_areas = np.array([self.areas[bp].sum() for bp in self.block_parcels])
        self.max_block_area = self.block_areas.max() + 1e-8

        # Load compactness from block_features.json
        self.block_compactness = np.zeros(len(self.block_parcels), dtype=np.float32)
        block_offset = 0
        for code in TOWNSHIP_CODES:
            feat_path = os.path.join(BLOCK_DIR, f'township_{code}', 'block_features.json')
            if not os.path.exists(feat_path):
                continue
            with open(feat_path) as f:
                saved_feats = json.load(f)
            for j, bf in enumerate(saved_feats):
                self.block_compactness[block_offset + j] = bf['compactness']
            block_offset += len(saved_feats)

        # Parcel-to-block mapping
        self.parcel_to_block = np.full(self.n_parcels, -1, dtype=np.int32)
        for bid, parcels in enumerate(self.block_parcels):
            self.parcel_to_block[parcels] = bid

        n_assigned = int((self.parcel_to_block >= 0).sum())
        n_blocks = len(self.block_parcels)

        # Per-township block counts
        for ti, code in enumerate(TOWNSHIP_CODES):
            n_tb = int((self.block_to_township == ti).sum())
            label = ALL_TOWNSHIPS[code]
            print(f"    {label}: {n_tb} blocks")

        print(f"  Total: {n_blocks} blocks, {n_assigned}/{self.n_parcels} parcels assigned")

    def _build_block_adjacency(self):
        """Build block adjacency graph from parcel adjacency (cross-township)."""
        n_blocks = len(self.block_parcels)
        adj_sets = [set() for _ in range(n_blocks)]

        for i in range(self.n_parcels):
            bi = self.parcel_to_block[i]
            if bi < 0:
                continue
            for j in self.adjacency[i]:
                bj = self.parcel_to_block[j]
                if bj >= 0 and bj != bi:
                    adj_sets[bi].add(bj)

        self.block_adj = [np.array(sorted(s), dtype=np.intp) for s in adj_sets]
        self.block_n_adj = np.array([len(a) for a in self.block_adj], dtype=np.int32)

        # Count cross-township block edges
        cross = 0
        for b in range(n_blocks):
            tb = self.block_to_township[b]
            for nb in self.block_adj[b]:
                if self.block_to_township[nb] != tb:
                    cross += 1
        self.n_cross_township_edges = cross // 2

    def _precompute_padded_arrays(self):
        """Pre-compute padded parcel index arrays for vectorized block feature computation.

        Creates fixed-size (n_blocks x max_parcels_per_block) arrays so that
        _get_block_features() can use batch numpy ops instead of Python loops.
        """
        n_blocks = len(self.block_parcels)
        self._block_sizes = np.array([len(bp) for bp in self.block_parcels], dtype=np.int32)
        max_bp = int(self._block_sizes.max())
        self._max_parcels_per_block = max_bp

        # Padded parcel indices: (n_blocks, max_bp), padded with 0
        # We'll use a mask to ignore padding positions
        self._pad_idx = np.zeros((n_blocks, max_bp), dtype=np.intp)
        self._pad_mask = np.zeros((n_blocks, max_bp), dtype=bool)
        for b in range(n_blocks):
            n = len(self.block_parcels[b])
            self._pad_idx[b, :n] = self.block_parcels[b]
            self._pad_mask[b, :n] = True

        # Pre-fetch static per-parcel data in padded form
        self._pad_slopes = self.slopes[self._pad_idx]   # (n_blocks, max_bp)
        self._pad_areas = self.areas[self._pad_idx]      # (n_blocks, max_bp)
        # Zero out padding positions
        self._pad_slopes[~self._pad_mask] = 0.0
        self._pad_areas[~self._pad_mask] = 0.0

        # Pre-compute padded block adjacency for vectorized neighbor features
        max_adj = int(self.block_n_adj.max()) if n_blocks > 0 else 0
        self._pad_adj = np.zeros((n_blocks, max(max_adj, 1)), dtype=np.intp)
        self._pad_adj_mask = np.zeros((n_blocks, max(max_adj, 1)), dtype=bool)
        for b in range(n_blocks):
            n_adj = len(self.block_adj[b])
            if n_adj > 0:
                self._pad_adj[b, :n_adj] = self.block_adj[b]
                self._pad_adj_mask[b, :n_adj] = True

    def _init_block_counters(self):
        """Initialize per-block available parcel counters."""
        for b, parcels in enumerate(self.block_parcels):
            types = self.land_use[parcels]
            self._block_farm_avail[b] = int(((types == FARMLAND) & ~self.swapped[parcels]).sum())
            self._block_forest_avail[b] = int(((types == FOREST) & ~self.swapped[parcels]).sum())

    # ==================================================================
    # Metrics
    # ==================================================================

    def _compute_metrics_full(self):
        """Compute slope/contiguity metrics from scratch."""
        fm = self.land_use == FARMLAND
        self.n_farmland = int(fm.sum())
        self.n_forest = int((self.land_use == FOREST).sum())

        self.total_weighted_slope = float((self.slopes[fm] * self.areas[fm]).sum())
        self.total_farm_area = float(self.areas[fm].sum())

        self.farmland_nbr_count = np.zeros(self.n_parcels, dtype=np.int32)
        for i in range(self.n_parcels):
            nbrs = self.adjacency[i]
            if len(nbrs) > 0:
                self.farmland_nbr_count[i] = int((self.land_use[nbrs] == FARMLAND).sum())
        self.total_farmland_adj = int(self.farmland_nbr_count[fm].sum())

    def _count_baimu_fang(self):
        """Count baimu fang patches via numpy-accelerated union-find (crosses township boundaries).

        Uses array-based union-find instead of Python BFS for better performance
        on large parcel counts (52k+).
        """
        n = self.n_parcels
        is_farm = self.land_use == FARMLAND

        # Union-Find with path compression (array-based)
        parent = np.arange(n, dtype=np.int32)
        rank = np.zeros(n, dtype=np.int32)

        def find(x):
            root = x
            while parent[root] != root:
                root = parent[root]
            # Path compression
            while parent[x] != root:
                parent[x], x = root, parent[x]
            return root

        # Union farmland neighbors
        for i in range(n):
            if not is_farm[i]:
                continue
            for j in self.adjacency[i]:
                if j > i and is_farm[j]:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        if rank[ri] < rank[rj]:
                            ri, rj = rj, ri
                        parent[rj] = ri
                        if rank[ri] == rank[rj]:
                            rank[ri] += 1

        # Aggregate areas by component root
        farm_indices = np.where(is_farm)[0]
        if len(farm_indices) == 0:
            return 0, 0.0

        roots = np.array([find(i) for i in farm_indices], dtype=np.int32)
        unique_roots, inverse = np.unique(roots, return_inverse=True)
        component_areas = np.zeros(len(unique_roots), dtype=np.float64)
        np.add.at(component_areas, inverse, self.areas[farm_indices])

        # Count baimu fang patches
        baimu_mask = component_areas >= self.baimu_threshold_m2
        return int(baimu_mask.sum()), float(component_areas[baimu_mask].sum())

    @property
    def avg_farmland_slope(self):
        return self.total_weighted_slope / max(self.total_farm_area, 1e-8)

    @property
    def contiguity(self):
        return self.total_farmland_adj / max(self.n_farmland, 1)

    # ==================================================================
    # Incremental swap updates
    # ==================================================================

    def _swap_to_forest(self, k):
        """Farmland -> Forest at parcel k."""
        self.total_farmland_adj -= self.farmland_nbr_count[k]
        self.total_weighted_slope -= self.slopes[k] * self.areas[k]
        self.total_farm_area -= self.areas[k]

        self.land_use[k] = FOREST
        self.n_farmland -= 1
        self.n_forest += 1

        for j in self.adjacency[k]:
            self.farmland_nbr_count[j] -= 1
            if self.land_use[j] == FARMLAND:
                self.total_farmland_adj -= 1

    def _swap_to_farmland(self, k):
        """Forest -> Farmland at parcel k."""
        self.land_use[k] = FARMLAND
        self.n_farmland += 1
        self.n_forest -= 1
        self.total_weighted_slope += self.slopes[k] * self.areas[k]
        self.total_farm_area += self.areas[k]

        self.total_farmland_adj += self.farmland_nbr_count[k]

        for j in self.adjacency[k]:
            self.farmland_nbr_count[j] += 1
            if self.land_use[j] == FARMLAND:
                self.total_farmland_adj += 1

    def _area_floor_allows_pair(self, farm_idx, forest_idx):
        """Return True if a farm->forest / forest->farm pair preserves area floor."""
        if self.cultivated_area_floor_m2 is None:
            return True
        next_area = self.total_farm_area - self.areas[farm_idx] + self.areas[forest_idx]
        return bool(next_area >= self.cultivated_area_floor_m2 - 1e-6)

    def _baimu_floor_allows_pair(self, farm_idx, forest_idx):
        """Return True if a proposed pair preserves the configured baimu floor.

        This is intentionally checked only during real pair execution, not in
        the block action mask, because recomputing connected components is an
        expensive global operation.
        """
        if self.baimu_area_floor_m2 is None:
            return True
        old_farm = self.land_use[farm_idx]
        old_forest = self.land_use[forest_idx]
        self.land_use[farm_idx] = FOREST
        self.land_use[forest_idx] = FARMLAND
        try:
            _, next_baimu_area = self._count_baimu_fang()
        finally:
            self.land_use[farm_idx] = old_farm
            self.land_use[forest_idx] = old_forest
        return bool(next_baimu_area >= self.baimu_area_floor_m2 - 1e-6)

    def _select_greedy_swap_pair(self, farm_idx, forest_idx, enforce_baimu_floor=True):
        """Select the greedy slope-improving pair, respecting area floor if active."""
        if len(farm_idx) == 0 or len(forest_idx) == 0:
            return None

        farm_scores = (
            self.slopes[farm_idx]
            - self.delta_conn * self.farmland_nbr_count[farm_idx]
        )
        forest_scores = (
            self.slopes[forest_idx]
            - self.gamma_conn * self.farmland_nbr_count[forest_idx]
        )

        if self.cultivated_area_floor_m2 is None and (
            self.baimu_area_floor_m2 is None or not enforce_baimu_floor
        ):
            best_farm = int(farm_idx[np.argmax(farm_scores)])
            best_forest = int(forest_idx[np.argmin(forest_scores)])
            if self.slopes[best_farm] <= self.slopes[best_forest]:
                return None
            return best_farm, best_forest

        farm_order = np.argsort(farm_scores)[::-1]
        forest_order = np.argsort(forest_scores)
        for farm_pos in farm_order:
            candidate_farm = int(farm_idx[farm_pos])
            for forest_pos in forest_order:
                candidate_forest = int(forest_idx[forest_pos])
                if self.slopes[candidate_farm] <= self.slopes[candidate_forest]:
                    continue
                if self._area_floor_allows_pair(candidate_farm, candidate_forest):
                    if enforce_baimu_floor and not self._baimu_floor_allows_pair(
                        candidate_farm, candidate_forest
                    ):
                        continue
                    return candidate_farm, candidate_forest
        return None

    def _block_has_area_feasible_swap(self, block_id):
        """Check whether a block has any slope-improving pair under area floor."""
        parcels = self.block_parcels[block_id]
        types = self.land_use[parcels]
        avail = ~self.swapped[parcels]

        farm_idx = parcels[(types == FARMLAND) & avail]
        forest_idx = parcels[(types == FOREST) & avail]
        return self._select_greedy_swap_pair(
            farm_idx, forest_idx, enforce_baimu_floor=False
        ) is not None

    # ==================================================================
    # Greedy execution engine
    # ==================================================================

    def _execute_greedy_in_block(self, block_id, max_swaps):
        """Connectivity-aware greedy paired swaps within a single block."""
        parcels = self.block_parcels[block_id]
        completed = 0

        for _ in range(max_swaps):
            types = self.land_use[parcels]
            avail = ~self.swapped[parcels]

            farm_mask = (types == FARMLAND) & avail
            forest_mask = (types == FOREST) & avail

            if not farm_mask.any() or not forest_mask.any():
                break

            farm_local = np.where(farm_mask)[0]
            forest_local = np.where(forest_mask)[0]

            farm_idx = parcels[farm_local]
            forest_idx = parcels[forest_local]

            pair = self._select_greedy_swap_pair(farm_idx, forest_idx)
            if pair is None:
                if self.baimu_area_floor_m2 is not None:
                    self._block_farm_avail[block_id] = 0
                    self._block_forest_avail[block_id] = 0
                break
            best_farm, best_forest = pair

            self._swap_to_forest(best_farm)
            self._swap_to_farmland(best_forest)
            self.swapped[best_farm] = True
            self.swapped[best_forest] = True
            completed += 1

            self._block_farm_avail[block_id] -= 1
            self._block_forest_avail[block_id] -= 1

        return completed

    # ==================================================================
    # Gymnasium API
    # ==================================================================

    def _get_block_features(self):
        """Per-block feature matrix (n_blocks x K_BLOCK=17). Vectorized."""
        n_blocks = self.n_blocks
        max_bp = self._max_parcels_per_block
        features = np.zeros((n_blocks, K_BLOCK), dtype=np.float32)

        # Fetch dynamic per-parcel data using padded indices
        pad_types = self.land_use[self._pad_idx]         # (n_blocks, max_bp)
        pad_swapped = self.swapped[self._pad_idx]        # (n_blocks, max_bp)

        # Masks: farmland/forest that are available and within real parcels
        fm_mask = (pad_types == FARMLAND) & (~pad_swapped) & self._pad_mask  # (n_blocks, max_bp)
        ff_mask = (pad_types == FOREST) & (~pad_swapped) & self._pad_mask

        # For farm area of all farmland (including swapped) -- needed for neighbor features
        all_fm_mask = (pad_types == FARMLAND) & self._pad_mask

        # Slopes and areas (static, pre-fetched with padding zeroed)
        slopes = self._pad_slopes  # (n_blocks, max_bp)
        areas = self._pad_areas

        # --- Per-block aggregates ---
        # Farm available
        fm_slopes = np.where(fm_mask, slopes, 0.0)
        fm_areas = np.where(fm_mask, areas, 0.0)
        farm_area = fm_areas.sum(axis=1)                  # (n_blocks,)
        farm_weighted = (fm_slopes * fm_areas).sum(axis=1)
        avg_farm = np.where(farm_area > 0, farm_weighted / farm_area, 0.0)

        # Farm slope std: E[x^2] - E[x]^2
        farm_w_sq = (fm_slopes**2 * fm_areas).sum(axis=1)
        farm_var = np.where(farm_area > 0,
                            farm_w_sq / farm_area - avg_farm**2, 0.0)
        farm_std = np.sqrt(np.maximum(farm_var, 0.0))

        # Top farm slope (max)
        top_farm = np.where(fm_mask, slopes, -np.inf).max(axis=1)
        top_farm = np.where(farm_area > 0, top_farm, 0.0)

        # Forest available
        ff_slopes = np.where(ff_mask, slopes, 0.0)
        ff_areas = np.where(ff_mask, areas, 0.0)
        forest_area = ff_areas.sum(axis=1)
        forest_weighted = (ff_slopes * ff_areas).sum(axis=1)
        avg_for = np.where(forest_area > 0, forest_weighted / forest_area, 0.0)

        # Bottom forest slope (min)
        bottom_forest = np.where(ff_mask, slopes, np.inf).min(axis=1)
        bottom_forest = np.where(forest_area > 0, bottom_forest, 0.0)

        # Best gain
        has_both = (farm_area > 0) & (forest_area > 0)
        best_gain = np.where(has_both, top_farm - bottom_forest, 0.0)

        # Block farm areas (all farmland, for neighbor features)
        block_farm_areas = np.where(all_fm_mask, areas, 0.0).sum(axis=1)

        # Fill features [0-12] vectorized
        inv_sr = 1.0 / self.slope_range
        features[:, 0] = (avg_farm - self.slope_min) * inv_sr
        features[:, 1] = (avg_for - self.slope_min) * inv_sr
        features[:, 2] = (avg_farm - avg_for) * inv_sr
        features[:, 3] = best_gain * inv_sr
        features[:, 4] = farm_std * inv_sr
        features[:, 5] = (top_farm - self.slope_min) * inv_sr
        features[:, 6] = (bottom_forest - self.slope_min) * inv_sr
        features[:, 7] = farm_area / self.max_block_area
        features[:, 8] = forest_area / self.max_block_area
        features[:, 9] = np.minimum(self._block_farm_avail,
                                     self._block_forest_avail).astype(np.float32) / \
                          np.maximum(self._block_sizes, 1).astype(np.float32)
        features[:, 10] = self.swaps_in_block / max(self.swaps_per_step, 1)
        features[:, 11] = self.block_compactness
        features[:, 12] = self.block_areas / self.max_block_area

        # Features [13-14]: neighbor investment and farm area (using padded adjacency)
        adj_swaps = self.swaps_in_block[self._pad_adj]  # (n_blocks, max_adj)
        adj_invested = np.where(self._pad_adj_mask, adj_swaps > 0, False).sum(axis=1)
        n_adj = self.block_n_adj.astype(np.float32)
        features[:, 13] = np.where(n_adj > 0, adj_invested / n_adj, 0.0)

        adj_farm = block_farm_areas[self._pad_adj]  # (n_blocks, max_adj)
        adj_farm_sum = np.where(self._pad_adj_mask, adj_farm, 0.0).sum(axis=1)
        features[:, 14] = np.where(n_adj > 0,
                                    adj_farm_sum / (self.max_block_area * n_adj), 0.0)

        # Features [15-16]
        features[:, 15] = block_farm_areas / self.max_block_area
        features[:, 16] = (self.swaps_in_block > 0).astype(np.float32)

        return features

    def _get_global_features(self):
        """County-level global feature vector (K_GLOBAL_COUNTY=12).

        Features [0-8]: same as Paper 3 BlockLevelEnv
        Features [9-11]: county-specific coordination signals
        """
        cur_slope = self.avg_farmland_slope
        cur_cont = self.contiguity
        n_invested = int((self.swaps_in_block > 0).sum())

        # Per-township investment fractions (vectorized with np.bincount)
        township_swaps = np.bincount(self.block_to_township,
                                     weights=self.swaps_in_block.astype(np.float64),
                                     minlength=self.n_townships)
        total_swaps = township_swaps.sum() + 1e-8

        # Investment entropy (how evenly budget is spread across townships)
        probs = township_swaps / total_swaps
        probs_safe = np.where(probs > 0, probs, 1.0)
        entropy = -float((probs * np.log(probs_safe)).sum())
        max_entropy = np.log(self.n_townships)  # uniform distribution

        # Max single-township fraction
        max_township_frac = float(township_swaps.max() / total_swaps)

        return np.array([
            # Base features (same as Paper 3)
            1.0 - self.step_count / self.max_steps,                              # [0] budget_remaining
            (cur_slope - self.slope_min) / self.slope_range,                     # [1] global_slope_norm
            cur_cont / 10.0,                                                     # [2] global_cont_norm
            self.step_count / self.max_steps,                                    # [3] step_frac
            (self.initial_slope - cur_slope) / (abs(self.initial_slope) + 1e-8), # [4] slope_improvement
            (cur_cont - self.initial_cont) / (abs(self.initial_cont) + 1e-8),   # [5] cont_improvement
            self.baimu_count / max(self.n_blocks / 10.0, 1.0),                  # [6] baimu_count_norm
            self.baimu_total_area / max(self.total_farm_area, 1e-8),             # [7] baimu_area_frac
            n_invested / self.n_blocks,                                          # [8] blocks_invested_frac
            # County-specific features
            entropy / (max_entropy + 1e-8),                                      # [9] investment_entropy
            0.0,  # placeholder: cross-township baimu ratio (computed lazily)    # [10]
            max_township_frac,                                                   # [11] max_township_frac
        ], dtype=np.float32)

    def _get_obs(self):
        """Build flat observation: [block_features | global_features]."""
        block_feats = self._get_block_features()
        global_feats = self._get_global_features()
        return np.concatenate([block_feats.ravel(), global_feats])

    def action_masks(self):
        """Boolean mask: True if block has swap potential."""
        mask = (self._block_farm_avail > 0) & (self._block_forest_avail > 0)
        if self.cultivated_area_floor_m2 is None:
            return mask

        constrained = mask.copy()
        for block_id in np.where(mask)[0]:
            constrained[block_id] = self._block_has_area_feasible_swap(block_id)
        return constrained

    def _cache_initial_state(self):
        """Cache initial state for fast reset."""
        self.initial_slope = self.avg_farmland_slope
        self.initial_cont = self.contiguity
        self.initial_baimu_count = self.baimu_count
        self.initial_baimu_area = self.baimu_total_area
        self.initial_farm_area = self.total_farm_area
        if self.cultivated_area_floor_delta_ha is not None:
            self.cultivated_area_floor_m2 = (
                self.initial_farm_area
                + self.cultivated_area_floor_delta_ha * 10000.0
            )
        if self.baimu_area_floor_delta_ha is not None:
            self.baimu_area_floor_m2 = (
                self.initial_baimu_area
                + self.baimu_area_floor_delta_ha * 10000.0
            )
        self._init_cache = {
            'land_use': self.land_use.copy(),
            'n_farmland': self.n_farmland,
            'n_forest': self.n_forest,
            'total_weighted_slope': self.total_weighted_slope,
            'total_farm_area': self.total_farm_area,
            'farmland_nbr_count': self.farmland_nbr_count.copy(),
            'total_farmland_adj': self.total_farmland_adj,
            'block_farm_avail': self._block_farm_avail.copy(),
            'block_forest_avail': self._block_forest_avail.copy(),
        }

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        c = self._init_cache
        self.land_use = c['land_use'].copy()
        self.n_farmland = c['n_farmland']
        self.n_forest = c['n_forest']
        self.total_weighted_slope = c['total_weighted_slope']
        self.total_farm_area = c['total_farm_area']
        self.farmland_nbr_count = c['farmland_nbr_count'].copy()
        self.total_farmland_adj = c['total_farmland_adj']
        self._block_farm_avail = c['block_farm_avail'].copy()
        self._block_forest_avail = c['block_forest_avail'].copy()

        self.swapped[:] = False
        self.budget_used = 0
        self.step_count = 0
        self.swaps_in_block[:] = 0

        self.baimu_count = self.initial_baimu_count
        self.baimu_total_area = self.initial_baimu_area

        self.prev_slope = self.initial_slope
        self.prev_cont = self.initial_cont
        self.prev_baimu_count = self.initial_baimu_count
        self.prev_baimu_area = self.initial_baimu_area

        obs = self._get_obs()
        info = {
            'avg_slope': self.avg_farmland_slope,
            'contiguity': self.contiguity,
            'baimu_count': self.baimu_count,
            'baimu_area_ha': self.baimu_total_area / 10000.0,
            'cultivated_area_ha': self.total_farm_area / 10000.0,
            'cultivated_area_change_ha': 0.0,
            'cultivated_area_change_pct': 0.0,
            'baimu_area_floor_delta_ha': self.baimu_area_floor_delta_ha,
            'baimu_area_floor_ha': (
                None if self.baimu_area_floor_m2 is None
                else self.baimu_area_floor_m2 / 10000.0
            ),
            'budget_used': 0,
        }
        return obs, info

    def step(self, action):
        block_id = int(action)

        completed = self._execute_greedy_in_block(block_id, self.swaps_per_step)
        self.budget_used += completed
        self.swaps_in_block[block_id] += completed
        self.step_count += 1

        # Baimu fang: recompute every N steps (expensive BFS/union-find)
        # Every step costs ~60-120ms; skipping most calls saves huge time
        baimu_interval = max(1, self.max_steps // 20)  # ~5% of steps
        if self.step_count % baimu_interval == 0 or self.step_count >= self.max_steps:
            self.baimu_count, self.baimu_total_area = self._count_baimu_fang()

        cur_slope = self.avg_farmland_slope
        cur_cont = self.contiguity

        slope_delta = (self.prev_slope - cur_slope) / (abs(self.initial_slope) + 1e-8)
        cont_delta = (cur_cont - self.prev_cont) / (abs(self.initial_cont) + 1e-8)
        baimu_area_delta = ((self.baimu_total_area - self.prev_baimu_area)
                            / (self.initial_farm_area + 1e-8))
        baimu_new_count = max(0, self.baimu_count - self.prev_baimu_count)

        reward = (self.slope_weight * slope_delta
                  + self.cont_weight * cont_delta
                  + self.baimu_weight * baimu_area_delta
                  + self.baimu_bonus * baimu_new_count)

        # Asymmetric penalty: extra cost when baimu area decreases
        if baimu_area_delta < 0:
            reward += self.baimu_area_penalty * baimu_area_delta  # negative * positive = penalty

        if completed == 0:
            reward -= 1.0

        self.prev_slope = cur_slope
        self.prev_cont = cur_cont
        self.prev_baimu_count = self.baimu_count
        self.prev_baimu_area = self.baimu_total_area

        terminated = self.step_count >= self.max_steps
        if not terminated:
            if not self.action_masks().any():
                terminated = True

        info = {
            'avg_slope': cur_slope,
            'contiguity': cur_cont,
            'baimu_count': self.baimu_count,
            'baimu_area_ha': self.baimu_total_area / 10000.0,
            'cultivated_area_ha': self.total_farm_area / 10000.0,
            'cultivated_area_change_ha': (
                self.total_farm_area - self.initial_farm_area
            ) / 10000.0,
            'cultivated_area_change_pct': 100.0 * (
                self.total_farm_area - self.initial_farm_area
            ) / (abs(self.initial_farm_area) + 1e-8),
            'cultivated_area_floor_delta_ha': self.cultivated_area_floor_delta_ha,
            'cultivated_area_floor_ha': (
                None if self.cultivated_area_floor_m2 is None
                else self.cultivated_area_floor_m2 / 10000.0
            ),
            'baimu_area_floor_delta_ha': self.baimu_area_floor_delta_ha,
            'baimu_area_floor_ha': (
                None if self.baimu_area_floor_m2 is None
                else self.baimu_area_floor_m2 / 10000.0
            ),
            'budget_used': self.budget_used,
            'completed_swaps': completed,
            'block_selected': block_id,
            'step': self.step_count,
            'slope_change_pct': 100.0 * (cur_slope - self.initial_slope) / (
                abs(self.initial_slope) + 1e-8),
            'cont_change': cur_cont - self.initial_cont,
            'baimu_count_change': self.baimu_count - self.initial_baimu_count,
            'baimu_area_change_ha': (self.baimu_total_area - self.initial_baimu_area) / 10000.0,
        }

        return self._get_obs(), float(reward), terminated, False, info

    # ==================================================================
    # Per-township analysis
    # ==================================================================

    def get_per_township_metrics(self):
        """Compute metrics breakdown per township (for evaluation analysis)."""
        results = {}
        for ti, code in enumerate(TOWNSHIP_CODES):
            t_parcels = self._township_parcel_indices[code]
            t_blocks = np.where(self.block_to_township == ti)[0]

            fm = self.land_use[t_parcels] == FARMLAND
            t_farm_area = float(self.areas[t_parcels[fm]].sum())
            t_weighted_slope = float((self.slopes[t_parcels[fm]] * self.areas[t_parcels[fm]]).sum())
            t_avg_slope = t_weighted_slope / max(t_farm_area, 1e-8)

            t_swaps = int(self.swaps_in_block[t_blocks].sum())
            t_invested = int((self.swaps_in_block[t_blocks] > 0).sum())

            results[code] = {
                'label': ALL_TOWNSHIPS[code],
                'n_blocks': len(t_blocks),
                'swaps_used': t_swaps,
                'blocks_invested': t_invested,
                'avg_farmland_slope': t_avg_slope,
                'farmland_area_ha': t_farm_area / 10000.0,
            }

        return results


# ======================================================================
# Quick test
# ======================================================================

if __name__ == '__main__':
    import time

    budget = 500
    sps = 5

    env = CountyLevelEnv(total_budget=budget, swaps_per_step=sps)
    obs, info = env.reset()
    print(f"\nObs shape: {obs.shape}")
    print(f"Action space: {env.action_space}")
    print(f"Valid actions: {env.action_masks().sum()} / {env.n_blocks}")

    # Benchmark baimu fang counting
    t0 = time.time()
    for _ in range(10):
        env._count_baimu_fang()
    baimu_time = (time.time() - t0) / 10
    print(f"Baimu fang BFS: {baimu_time*1000:.1f} ms per call")

    # Run a few random steps
    print("\nRunning 5 random steps...")
    total_reward = 0
    for i in range(5):
        mask = env.action_masks()
        valid = np.where(mask)[0]
        action = np.random.choice(valid)
        obs, reward, done, truncated, info = env.step(action)
        total_reward += reward
        township_idx = env.block_to_township[action]
        township_code = TOWNSHIP_CODES[township_idx]
        print(f"  Step {i+1}: block={action} ({ALL_TOWNSHIPS[township_code]}), "
              f"swaps={info['completed_swaps']}, reward={reward:.2f}, "
              f"slope={info['slope_change_pct']:+.3f}%")

    print(f"\nTotal reward: {total_reward:.2f}")
    print(f"Budget used: {info['budget_used']}")

    # Per-township analysis
    print("\nPer-township metrics:")
    metrics = env.get_per_township_metrics()
    for code, m in metrics.items():
        print(f"  {m['label']}: {m['swaps_used']} swaps, "
              f"{m['blocks_invested']}/{m['n_blocks']} blocks invested")
