import numpy as np

from farmland_mpc import sample


class _FakeEnv:
    n_blocks = 2
    n_parcels = 4
    max_steps = 1


def test_sample_passes_cultivated_area_floor_to_county_env(tmp_path, monkeypatch):
    captured = {}

    def fake_make_env(**kwargs):
        captured.update(kwargs)
        return _FakeEnv()

    monkeypatch.setattr(sample, "_import_make_env", lambda env_kind: fake_make_env)
    monkeypatch.setattr(
        sample,
        "_collect_transitions",
        lambda env, n_episodes, seed_offset, say: {
            "block_features": np.zeros((1, 2, 17), dtype=np.float32),
            "global_features": np.zeros((1, 12), dtype=np.float32),
            "actions": np.zeros((1,), dtype=np.int64),
            "rewards": np.zeros((1,), dtype=np.float32),
            "next_block_features": np.zeros((1, 2, 17), dtype=np.float32),
            "next_global_features": np.zeros((1, 12), dtype=np.float32),
        },
    )
    monkeypatch.setattr(
        sample,
        "_collect_pairwise",
        lambda env, n_states, n_actions, seed, max_outer_episodes, say: {
            "states_bf": np.zeros((1, 2, 17), dtype=np.float32),
            "states_gf": np.zeros((1, 12), dtype=np.float32),
            "actions": np.zeros((1, 1), dtype=np.int64),
            "rewards": np.zeros((1, 1), dtype=np.float32),
        },
    )

    summary = sample.run(
        prepared_dir=tmp_path,
        n_transition_episodes=1,
        n_pairwise_states=1,
        n_pairwise_actions=1,
        cultivated_area_floor_delta_ha=0,
    )

    assert captured["cultivated_area_floor_delta_ha"] == 0.0
    assert summary["config"]["constraint_overrides"] == {"cultivated_area_floor_delta_ha": 0.0}
