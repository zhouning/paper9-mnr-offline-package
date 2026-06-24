"""Natural-resources restoration environment, structurally parallel to CountyLevelEnv.

Generalises the farmland-consolidation MPC pipeline to a non-farmland decision
problem: prioritised selection of spatial planning units for ecological
restoration / abandoned-mine reclamation under a budget and multi-objective
reward. The action space is a finite categorical of size ``n_units``;
``action_masks()`` excludes already-selected units and (optionally)
budget-violating units. State is per-unit attribute features plus a global
state vector. Snapshot/restore is supported for pairwise sampling.

This env is consumed by the same ``farmland_mpc.mpc_plan`` and
``farmland_mpc.sample`` pipelines as ``CountyLevelEnv``; see
``farmland_mpc.restoration_blocks_env.make_restoration_env`` for the factory
that the package's ``--env`` CLI flag selects.

Differences from CountyLevelEnv:
  - Action is a one-time selection (selected units cannot be re-selected) —
    monotonic, single-assignment, vs CountyLevelEnv's reversible swaps.
  - Reward is the sum of per-unit risk-reduction / habitat-connectivity /
    water / cost terms read from a per-unit attribute table.
  - State features are read from an attribute CSV rather than recomputed
    from cadastral geometry; no parcel-level geometry is involved.

State conventions (so mpc_plan can consume the env unchanged):
  - block_features:  (n_units, K_UNIT=17) float32, padded with zeros if the
                     attribute table is narrower.
  - global_features: (K_GLOBAL=12) float32. First slot is fraction of budget
                     remaining; second is fraction of units already selected;
                     remaining slots are running cumulative reward components.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces


K_UNIT = 17  # match CountyLevelEnv K_BLOCK so ensembles can be cross-loaded
K_GLOBAL = 12


@dataclass
class _Snapshot:
    selected: np.ndarray
    cumulative_reward_components: np.ndarray
    budget_used: float
    step_count: int
    cost_arr: np.ndarray
    risk_dynamic: np.ndarray
    delayed_buffer: list


class RestorationEnv(gym.Env):
    """Region-agnostic ecological-restoration env.

    Parameters
    ----------
    units : pd.DataFrame
        Per-unit attribute table. Must contain ``unit_id`` and a
        ``candidate`` column (1 = eligible action, 0 = always masked) plus
        whichever feature/reward columns the scenario uses.
    adjacency : pd.DataFrame
        Edge list with ``source``, ``target`` columns; used for
        connectivity-bonus rewards.
    feature_cols : list[str]
        Attribute columns to use as per-unit numeric features. Excess columns
        are truncated; insufficient columns are zero-padded to ``K_UNIT``.
    reward_terms : dict[str, float]
        Linear combination weights, e.g.
        ``{'risk_reduction': 0.45, 'water_priority': 0.25,
            'connectivity': 0.20, 'cost_penalty': -0.10}``.
        Each key must be a column of ``units`` except ``connectivity``,
        which is computed dynamically as ``num adjacent already-selected
        units / max_degree``.
    budget : float
        Hard budget on cumulative ``cost_col`` of selected units.
    cost_col : str
        Column name that the budget tracks.
    max_steps : int
        Episode length. Truncates if all candidates are masked earlier.
    """

    metadata = {"render_modes": []}

    def __init__(self,
                 units: pd.DataFrame,
                 adjacency: pd.DataFrame,
                 feature_cols: list[str],
                 reward_terms: dict[str, float],
                 budget: float,
                 cost_col: str,
                 max_steps: int = 50,
                 reward_profile: str = "default",
                 reward_profile_params: dict | None = None,
                 flowline_downstream: dict[int, list[int]] | None = None):
        super().__init__()
        if "unit_id" not in units.columns:
            raise ValueError("units DataFrame must have a 'unit_id' column")
        units = units.sort_values("unit_id").reset_index(drop=True)
        self.units = units
        self.n_units = len(units)
        self.n_parcels = self.n_units  # alias for mpc_plan compatibility
        self.n_blocks = self.n_units   # alias for ensemble batch_predict
        self.max_steps = int(max_steps)
        self.budget = float(budget)
        self.cost_col = cost_col

        # ---- reward profile (controls how step reward is computed) ----
        # 'default' -- the original linear-attribute-lookup reward used in §6.5.
        #              σ_a is large vs σ_s, so MSE training already learns to rank.
        # 'connectivity_dominant' -- weight 0.7 on connectivity + non-linear
        #              "cluster bonus" when num_neighbours_selected >= 3.
        #              Reduces σ_a because reward depends heavily on episode state.
        # 'watershed' -- selecting an upstream unit increases all downstream units'
        #              effective risk_index by +0.5. Trajectory-dependent reward;
        #              greedy methods cannot capture this.
        # 'scale_economy' -- unit's effective cost depends on number of already-
        #              selected units within its 2-hop neighbourhood. Combinatorial
        #              budget interaction.
        # 'delayed' -- reward is partially deferred: at step t, the agent only
        #              receives 30% of the immediate per-unit reward; the remaining
        #              70% is paid at step t+H_DEFER if the chosen unit and its
        #              downstream/connectivity neighbours have been "supported".
        #              Pure horizon-dependence; greedy completely fails.
        self.reward_profile = reward_profile
        self.reward_profile_params = dict(reward_profile_params or {})

        # Build per-unit feature matrix once (constant across an episode --
        # only the action mask and global state evolve).
        self.feature_cols = feature_cols
        feat = np.zeros((self.n_units, K_UNIT), dtype=np.float32)
        for j, c in enumerate(feature_cols[:K_UNIT]):
            if c not in units.columns:
                continue
            v = units[c].astype(float).to_numpy()
            v = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
            feat[:, j] = v.astype(np.float32)
        # Standardise per column to zero mean unit variance for numerical
        # stability under the same MSE training as farmland.
        for j in range(K_UNIT):
            col = feat[:, j]
            mu, sd = float(col.mean()), float(col.std())
            if sd > 1e-6:
                feat[:, j] = (col - mu) / sd
        self._unit_features = feat
        self._candidate_mask = (units.get("candidate", pd.Series([1] * self.n_units))
                                .astype(int).to_numpy().astype(bool))

        # Adjacency as scipy-style csr would be cleaner but keep numpy for
        # zero extra dependency.
        self._adj_neighbours = [[] for _ in range(self.n_units)]
        if "source" in adjacency.columns and "target" in adjacency.columns:
            for s, t in zip(adjacency["source"].astype(int),
                            adjacency["target"].astype(int)):
                if 0 <= s < self.n_units and 0 <= t < self.n_units:
                    self._adj_neighbours[s].append(int(t))
                    self._adj_neighbours[t].append(int(s))
        self._max_degree = max((len(nb) for nb in self._adj_neighbours), default=1)

        # 2-hop neighbourhood (used by scale_economy profile)
        self._adj_2hop: list[set[int]] = []
        for u in range(self.n_units):
            two_hop = set(self._adj_neighbours[u])
            for v in self._adj_neighbours[u]:
                two_hop.update(self._adj_neighbours[v])
            two_hop.discard(u)
            self._adj_2hop.append(two_hop)

        # Flowline downstream graph (used by watershed profile). If not provided,
        # build a synthetic one from row/col ordering so synthetic case has a
        # downstream concept too: lower row index = upstream, downstream =
        # neighbours with strictly larger row.
        if flowline_downstream is not None:
            self._downstream = {int(k): list(v) for k, v in flowline_downstream.items()}
        else:
            self._downstream = self._infer_downstream_from_rowcol(units)

        # Reward weights and column references
        self.reward_terms = dict(reward_terms)
        self._cost_arr = (units[cost_col].astype(float).to_numpy()
                          if cost_col in units.columns
                          else np.zeros(self.n_units, dtype=float))
        self._cost_arr_base = self._cost_arr.copy()  # immutable baseline for scale_economy
        self._reward_cols: dict[str, np.ndarray] = {}
        for k in reward_terms:
            if k == "connectivity" or k == "cost_penalty":
                continue
            if k not in units.columns:
                self._reward_cols[k] = np.zeros(self.n_units, dtype=float)
            else:
                self._reward_cols[k] = units[k].astype(float).to_numpy()
        # Watershed-augmented risk index: a copy that gets bumped when
        # upstream units are selected
        self._risk_dynamic = (self._reward_cols.get("risk_index",
                              self._reward_cols.get("risk_reduction",
                              np.zeros(self.n_units))).copy())

        # Gym spaces
        obs_dim = self.n_units * K_UNIT + K_GLOBAL
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf,
                                            shape=(obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(self.n_units)

        # Episode state
        self.selected = np.zeros(self.n_units, dtype=bool)
        self.budget_used = 0.0
        self.step_count = 0
        self._cum_reward_components = np.zeros(8, dtype=np.float64)
        self._rng = np.random.default_rng(0)

    # ------------------------------------------------------------------
    # gym API
    # ------------------------------------------------------------------
    def reset(self, *, seed=None, options=None):  # noqa: D401
        super().reset(seed=seed)
        if seed is not None:
            self._rng = np.random.default_rng(int(seed))
        self.selected[:] = False
        self.budget_used = 0.0
        self.step_count = 0
        self._cum_reward_components[:] = 0.0
        # Reset profile-specific dynamic state
        self._cost_arr = self._cost_arr_base.copy()
        self._risk_dynamic = (self._reward_cols.get("risk_index",
                              self._reward_cols.get("risk_reduction",
                              np.zeros(self.n_units))).copy())
        self._delayed_buffer = []  # for delayed profile: list of (step, action, payout)
        return self._get_obs(), {
            "n_units": self.n_units,
            "n_candidates": int(self._candidate_mask.sum()),
            "budget": self.budget,
            "reward_profile": self.reward_profile,
        }

    # ------------------------------------------------------------------
    # Reward-profile machinery (M1: routes per-step reward computation)
    # ------------------------------------------------------------------
    @staticmethod
    def _infer_downstream_from_rowcol(units: pd.DataFrame) -> dict[int, list[int]]:
        """For cases without an explicit hydrological flowline, build a
        synthetic 'downstream' graph: a unit's downstream neighbours are the
        4-adjacent (row±1, col±1) units that lie strictly south or east of it.
        This gives a deterministic spatial flow for testing watershed effects
        and matches the way Buchanan's NHD flowlines are oriented (south flowing).
        """
        if "row" not in units.columns or "col" not in units.columns:
            return {}
        rows = units["row"].astype(int).to_numpy()
        cols = units["col"].astype(int).to_numpy()
        ids  = units["unit_id"].astype(int).to_numpy()
        rc_to_id = {(int(r), int(c)): int(u) for r, c, u in zip(rows, cols, ids)}
        out: dict[int, list[int]] = {}
        for r, c, u in zip(rows, cols, ids):
            ds = []
            for (dr, dc) in [(1, 0), (0, 1)]:  # south, east
                nb = rc_to_id.get((int(r) + dr, int(c) + dc))
                if nb is not None:
                    ds.append(int(nb))
            out[int(u)] = ds
        return out

    def _compute_step_reward(self, a: int, cost: float) -> dict[str, float]:
        """Dispatch to the appropriate reward profile and return the per-step
        component breakdown. Side effects on profile-specific state
        (e.g. dynamic risk under watershed, dynamic cost under scale_economy)
        are applied here so subsequent actions see them.
        """
        if self.reward_profile == "default":
            return self._reward_default(a, cost)
        if self.reward_profile == "connectivity_dominant":
            return self._reward_connectivity_dominant(a, cost)
        if self.reward_profile == "watershed":
            return self._reward_watershed(a, cost)
        if self.reward_profile == "scale_economy":
            return self._reward_scale_economy(a, cost)
        if self.reward_profile == "delayed":
            return self._reward_delayed(a, cost)
        raise ValueError(f"unknown reward_profile={self.reward_profile!r}")

    def _reward_default(self, a: int, cost: float) -> dict[str, float]:
        """Original linear-attribute-lookup reward (Buchanan/synthetic original)."""
        components = {}
        for term, w in self.reward_terms.items():
            if term == "cost_penalty":
                components[term] = w * (cost / max(self.budget, 1e-6))
            elif term == "connectivity":
                nbrs = self._adj_neighbours[a]
                if nbrs:
                    frac_sel = sum(1.0 for n in nbrs if self.selected[n]) / len(nbrs)
                else:
                    frac_sel = 0.0
                components[term] = w * frac_sel
            else:
                components[term] = w * float(self._reward_cols[term][a])
        return components

    def _reward_connectivity_dominant(self, a: int, cost: float) -> dict[str, float]:
        """Profile 1: heavily weighted connectivity + non-linear cluster bonus.

        Mirrors farmland's small-σ_a regime by making the per-unit attribute
        contribution small (only 0.10 each on risk and water) while adding
        a state-dependent connectivity term that explodes at a threshold.
        Predicted to bring back ranking failure on MSE-only training.
        """
        components = {}
        nbrs = self._adj_neighbours[a]
        nbrs_selected = sum(1 for n in nbrs if self.selected[n]) if nbrs else 0
        # ---- linear per-attribute terms (small) ----
        # Use the same attribute columns as default but at much smaller weights
        for term in self.reward_terms:
            if term in ("connectivity", "cost_penalty"):
                continue
            v = float(self._reward_cols[term][a])
            components[term] = 0.10 * v  # was 0.45 / 0.25 / 0.20 in default
        # ---- connectivity (large, non-linear at threshold) ----
        frac_sel = (nbrs_selected / len(nbrs)) if nbrs else 0.0
        threshold_bonus = 5.0 if nbrs_selected >= 3 else 0.0
        components["connectivity"] = 0.70 * frac_sel + threshold_bonus
        components["cost_penalty"] = -0.10 * (cost / max(self.budget, 1e-6))
        return components

    def _reward_watershed(self, a: int, cost: float) -> dict[str, float]:
        """Profile 2: trajectory-dependent risk via flowline propagation.

        When an upstream unit is selected, its downstream descendants' risk
        index is permanently boosted by `boost`. Greedy/MILP cannot capture this
        because they treat each unit's reward as static; MPC's H=5 lookahead
        can plan to select an upstream unit early to benefit later downstream
        selections. The dynamic risk array `self._risk_dynamic` is updated
        in-place after each commit.
        """
        components = {}
        # Use the dynamic risk (which may have been bumped by upstream selections)
        risk_now = float(self._risk_dynamic[a])
        components["risk_index" if "risk_index" in self.reward_terms else "risk_reduction"] = 0.45 * risk_now

        for term in self.reward_terms:
            if term in ("risk_index", "risk_reduction", "connectivity", "cost_penalty"):
                continue
            components[term] = self.reward_terms[term] * float(self._reward_cols[term][a])

        nbrs = self._adj_neighbours[a]
        if nbrs:
            frac_sel = sum(1.0 for n in nbrs if self.selected[n]) / len(nbrs)
        else:
            frac_sel = 0.0
        components["connectivity"] = 0.20 * frac_sel
        components["cost_penalty"] = -0.10 * (cost / max(self.budget, 1e-6))

        # ---- side effect: bump downstream risks ----
        boost = float(self.reward_profile_params.get("watershed_boost", 0.5))
        for ds in self._downstream.get(a, []):
            self._risk_dynamic[ds] += boost
        return components

    def _reward_scale_economy(self, a: int, cost: float) -> dict[str, float]:
        """Profile 3: combinatorial cost interaction.

        A unit's *effective* cost depends on how many of its 2-hop neighbours
        are already selected (regional restoration scale economy). We compute
        the discount at commit time, then update neighbouring units' costs
        for downstream queries. Greedy/MILP cannot model this directly without
        re-formulating the problem with quadratic constraints.
        """
        components = {}
        # Standard linear attributes at default weights
        for term, w in self.reward_terms.items():
            if term in ("connectivity", "cost_penalty"):
                continue
            components[term] = w * float(self._reward_cols[term][a])
        nbrs = self._adj_neighbours[a]
        if nbrs:
            frac_sel = sum(1.0 for n in nbrs if self.selected[n]) / len(nbrs)
        else:
            frac_sel = 0.0
        components["connectivity"] = 0.20 * frac_sel
        components["cost_penalty"] = -0.10 * (cost / max(self.budget, 1e-6))

        # ---- side effect: discount neighbouring 2-hop unit costs ----
        discount = float(self.reward_profile_params.get("scale_discount_per_neighbour", 0.05))
        # cap at 50% off
        for nb in self._adj_2hop[a]:
            self._cost_arr[nb] = max(self._cost_arr[nb] * (1.0 - discount),
                                     self._cost_arr_base[nb] * 0.5)
        return components

    def _reward_delayed(self, a: int, cost: float) -> dict[str, float]:
        """Profile 4: delayed reward — only 30% paid immediately; 70% paid
        H_DEFER steps later iff the chosen unit's downstream OR connectivity
        neighbour-set has at least one additional selection in the meantime.
        Pure horizon-dependence: greedy methods cannot capture the deferred
        70%; MPC with H ≥ H_DEFER can, in principle, plan for it.
        """
        immediate_frac = float(self.reward_profile_params.get("immediate_frac", 0.30))
        h_defer = int(self.reward_profile_params.get("h_defer", 5))
        # Compute the *full* per-step contribution as in default
        full = self._reward_default(a, cost)
        immediate = {k: immediate_frac * v for k, v in full.items()}
        deferred_total = sum(v for v in full.values()) - sum(immediate.values())
        # Schedule the deferred payout to be released at step (current+h_defer)
        # if a "support condition" is satisfied -- we record the action and
        # check the condition then. Keep it simple: record and check later.
        self._delayed_buffer.append({
            "due_at_step":   self.step_count + h_defer,
            "action":        a,
            "payout":        deferred_total,
        })
        # Now release any deferred items whose due step has arrived
        components = dict(immediate)
        retained = []
        for item in self._delayed_buffer:
            if item["due_at_step"] == self.step_count:
                # Check support: at least one of the unit's neighbours OR
                # downstream descendants must have been selected since the
                # original commit.
                support_ok = any(self.selected[n] for n in self._adj_neighbours[item["action"]]) \
                    or any(self.selected[n] for n in self._downstream.get(item["action"], []))
                if support_ok:
                    components["delayed_payout"] = components.get("delayed_payout", 0.0) + item["payout"]
                # else: forfeit the deferred portion
            elif item["due_at_step"] > self.step_count:
                retained.append(item)
            # if due_at_step < step_count: dropped (forfeit, shouldn't happen)
        self._delayed_buffer = retained
        return components

    def step(self, action):
        a = int(action)
        if a < 0 or a >= self.n_units:
            raise ValueError(f"action {a} out of range [0, {self.n_units})")
        # If the action is already masked, fall back to a small negative reward
        # rather than raising, to mirror CountyLevelEnv's "wasted action" handling.
        mask = self.action_masks()
        if not mask[a]:
            self.step_count += 1
            terminated = (not mask.any()) or self.step_count >= self.max_steps
            return self._get_obs(), -1.0, terminated, False, {"wasted": True}

        cost = float(self._cost_arr[a])
        # commit selection
        self.selected[a] = True
        self.budget_used += cost
        self.step_count += 1

        # Compute per-step reward via the active reward profile
        components = self._compute_step_reward(a, cost)
        # accumulate (first 8 components only -- enough for global state)
        keys = list(components.keys())
        for j, k in enumerate(keys[:len(self._cum_reward_components)]):
            self._cum_reward_components[j] += components[k]
        reward = float(sum(components.values()))

        info = {
            "components": components,
            "selected_id": a,
            "budget_used": self.budget_used,
        }
        # If post-action no candidate is selectable, terminate.
        post_mask = self.action_masks()
        terminated = (not post_mask.any()) or self.step_count >= self.max_steps
        return self._get_obs(), reward, terminated, False, info

    def action_masks(self):
        m = self._candidate_mask.copy()
        m &= ~self.selected
        if self.budget_used >= self.budget - 1e-9:
            return np.zeros(self.n_units, dtype=bool)
        # also mask units that would individually exceed remaining budget
        remaining = self.budget - self.budget_used
        m &= (self._cost_arr <= remaining + 1e-9)
        return m

    # ------------------------------------------------------------------
    # observations (mpc_plan / sample compatibility)
    # ------------------------------------------------------------------
    def _get_block_features(self):
        return self._unit_features.copy()

    def _get_global_features(self):
        gf = np.zeros(K_GLOBAL, dtype=np.float32)
        gf[0] = float(1.0 - self.budget_used / max(self.budget, 1e-6))
        gf[1] = float(self.selected.sum() / max(self.n_units, 1))
        gf[2] = float(self.step_count / max(self.max_steps, 1))
        n_components = min(len(self._cum_reward_components), K_GLOBAL - 3)
        gf[3:3 + n_components] = self._cum_reward_components[:n_components]
        return gf

    def _get_obs(self):
        return np.concatenate([
            self._unit_features.ravel(),
            self._get_global_features(),
        ]).astype(np.float32)

    # ------------------------------------------------------------------
    # snapshot / restore (sample.py uses this for pairwise generation)
    # ------------------------------------------------------------------
    @property
    def land_use(self) -> np.ndarray:
        """Alias for ``selected`` so ``mpc_plan`` can dump trajectory tensors uniformly."""
        return self.selected.astype(np.int8)

    def snapshot(self):
        return _Snapshot(
            selected=self.selected.copy(),
            cumulative_reward_components=self._cum_reward_components.copy(),
            budget_used=float(self.budget_used),
            step_count=int(self.step_count),
            cost_arr=self._cost_arr.copy(),
            risk_dynamic=self._risk_dynamic.copy(),
            delayed_buffer=[dict(item) for item in getattr(self, "_delayed_buffer", [])],
        )

    def restore(self, snap: _Snapshot):
        self.selected = snap.selected.copy()
        self._cum_reward_components = snap.cumulative_reward_components.copy()
        self.budget_used = float(snap.budget_used)
        self.step_count = int(snap.step_count)
        self._cost_arr = snap.cost_arr.copy()
        self._risk_dynamic = snap.risk_dynamic.copy()
        self._delayed_buffer = [dict(item) for item in snap.delayed_buffer]


def make_restoration_env(prepared_dir: str | Path,
                         **kwargs) -> RestorationEnv:
    """Factory loading scenario_config.json + attributes/adjacency from a prepared/ dir.

    Same shape contract as ``farmland_mpc.blocks_env.make_env``: takes a
    prepared directory path and returns a ready-to-run env, all reward weights
    and feature columns read from on-disk JSON so the env is fully data-driven.

    The prepared/ dir is expected to contain:
      - scenario_config.json (output of restoration_prepare; reward_terms,
        budget, cost_col, max_steps, feature_cols)
      - attributes.csv      (one row per unit; numeric features + reward cols)
      - adjacency.csv       (source,target,...)
    """
    prepared_dir = Path(prepared_dir)
    cfg = json.loads((prepared_dir / "scenario_config.json").read_text())
    units = pd.read_csv(prepared_dir / "attributes.csv")
    adjacency = pd.read_csv(prepared_dir / "adjacency.csv")
    return RestorationEnv(
        units=units,
        adjacency=adjacency,
        feature_cols=cfg["feature_cols"],
        reward_terms=cfg["reward_terms"],
        budget=cfg.get("budget", cfg.get("budget_proxy", 1e9)),
        cost_col=cfg.get("cost_col", "restoration_cost_proxy"),
        max_steps=cfg.get("max_steps", 50),
        reward_profile=cfg.get("reward_profile", "default"),
        reward_profile_params=cfg.get("reward_profile_params"),
        flowline_downstream=cfg.get("flowline_downstream"),
    )
