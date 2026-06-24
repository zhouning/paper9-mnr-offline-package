"""ONNX-based ensemble runner: drop-in replacement for
EnsembleTransitionModel.predict / mpc_planner.batch_predict.

Why separate module: keeps onnxruntime details out of the MPC loop, so
mpc_plan.py reads like the research script.
"""
import os
import glob
from typing import List, Tuple

import numpy as np


class EnsembleOrtRunner:
    """Loads N *.onnx members and exposes a torch-free batch_predict().

    Usage:
        ens = EnsembleOrtRunner("path/to/models", n_threads=8)
        nbf, ngf, mean_r, std_r = ens.batch_predict(bf, gf, actions)

    All inputs are numpy; outputs are numpy. Matches the signature of
    mpc_planner.batch_predict() so MPC code can use this verbatim.
    """

    def __init__(self, onnx_dir: str, n_threads: int = 0):
        import onnxruntime as ort
        paths = sorted(glob.glob(os.path.join(onnx_dir, "*.onnx")))
        if not paths:
            raise FileNotFoundError(f"No *.onnx found under {onnx_dir}")

        sess_opt = ort.SessionOptions()
        if n_threads > 0:
            sess_opt.intra_op_num_threads = n_threads
            sess_opt.inter_op_num_threads = 1
        self._sessions = [
            ort.InferenceSession(p, sess_opt, providers=["CPUExecutionProvider"])
            for p in paths
        ]
        self._paths = paths
        outputs = self._sessions[0].get_outputs()
        self._reward_output_name = outputs[2].name if len(outputs) >= 3 else "reward"

        # Read the n_blocks dimension from member 0's block_features input.
        # Shape is (batch, n_blocks, K_BLOCK); n_blocks is statically baked in.
        bf_input = self._sessions[0].get_inputs()[0]
        # Shape entries are int for static, str for dynamic
        try:
            self._n_blocks = int(bf_input.shape[1])
        except (TypeError, ValueError):
            self._n_blocks = None  # somehow dynamic; can't pre-validate

    @property
    def n_blocks(self):
        """The n_blocks dimension baked into the ONNX graph, or None if dynamic."""
        return self._n_blocks

    def assert_compatible(self, env_n_blocks: int):
        """Raise a clear error if env's n_blocks doesn't match the ONNX ensemble.

        Ensembles bake n_blocks statically into TransitionModel's action
        embedding table, so an ensemble trained on one region cannot be
        reused on another; you must train a region-specific ensemble via
        Tool 3.
        """
        if self._n_blocks is not None and env_n_blocks != self._n_blocks:
            raise RuntimeError(
                f"ONNX ensemble was trained with n_blocks={self._n_blocks}, "
                f"but the env has n_blocks={env_n_blocks}. The action "
                "embedding dimension is fixed at training time. You must "
                "either (a) point Tool 4 at an ensemble trained on this "
                "region (run Tool 3), or (b) use the matching prepared_dir "
                "for the ensemble you have."
            )

    @property
    def n_members(self) -> int:
        return len(self._sessions)

    @property
    def paths(self) -> List[str]:
        return list(self._paths)

    def batch_predict(
        self,
        block_features: np.ndarray,   # (B, n_blocks, K_BLOCK) float32
        global_features: np.ndarray,  # (B, K_GLOBAL) float32
        actions: np.ndarray,          # (B,) int64
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return (next_bf_mean, next_gf_mean, reward_mean, reward_std)."""
        bf = np.ascontiguousarray(block_features, dtype=np.float32)
        gf = np.ascontiguousarray(global_features, dtype=np.float32)
        a  = np.ascontiguousarray(actions, dtype=np.int64)

        feeds = {"block_features": bf, "global_features": gf, "action": a}
        nbf_sum = None
        ngf_sum = None
        r_sum = None
        r_sq_sum = None
        for sess in self._sessions:
            nbf, ngf, r = sess.run(None, feeds)
            r = r.squeeze(-1)
            if nbf_sum is None:
                nbf_sum = np.array(nbf, dtype=np.float32, copy=True)
                ngf_sum = np.array(ngf, dtype=np.float32, copy=True)
                r_sum = np.array(r, dtype=np.float64, copy=True)
                r_sq_sum = r_sum * r_sum
            else:
                nbf_sum += nbf
                ngf_sum += ngf
                r_sum += r
                r_sq_sum += r * r

        n = np.float32(len(self._sessions))
        n_reward = float(len(self._sessions))
        r_mean = r_sum / n
        r_var = np.maximum(r_sq_sum / n_reward - r_mean * r_mean, 0.0)
        np.divide(nbf_sum, n, out=nbf_sum)
        np.divide(ngf_sum, n, out=ngf_sum)
        return (
            nbf_sum,
            ngf_sum,
            r_mean,
            np.sqrt(r_var).astype(np.float32, copy=False),
        )

    def batch_predict_rewards(
        self,
        block_features: np.ndarray,
        global_features: np.ndarray,
        actions: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return only ensemble reward mean/std without materialising next states."""
        bf = np.ascontiguousarray(block_features, dtype=np.float32)
        gf = np.ascontiguousarray(global_features, dtype=np.float32)
        a = np.ascontiguousarray(actions, dtype=np.int64)

        feeds = {"block_features": bf, "global_features": gf, "action": a}
        r_sum = None
        r_sq_sum = None
        for sess in self._sessions:
            (r,) = sess.run([self._reward_output_name], feeds)
            r = r.squeeze(-1)
            if r_sum is None:
                r_sum = np.array(r, dtype=np.float64, copy=True)
                r_sq_sum = r_sum * r_sum
            else:
                r_sum += r
                r_sq_sum += r * r

        n = float(len(self._sessions))
        r_mean = r_sum / n
        r_var = np.maximum(r_sq_sum / n - r_mean * r_mean, 0.0)
        return r_mean, np.sqrt(r_var).astype(np.float32, copy=False)
