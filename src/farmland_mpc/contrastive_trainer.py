"""Vendored ContrastiveTransitionTrainer.

Trainer for the contrastive world model. Uses the local
core.transition_model.

Loss = MSE_block + MSE_global + 0.1 * MSE_reward + lambda_rank * RankingLoss

RankingLoss: pairwise margin ranking on (a_i, a_j) at the same state s.
If r_true[i] > r_true[j], we want pred_r[i] > pred_r[j] + margin.
"""
import logging
from typing import Optional

import numpy as np
import torch
import torch.nn as nn

try:
    from farmland_mpc.transition_model import TransitionModel  # noqa: F401  (used by typing)
except ImportError:
    from core.transition_model import TransitionModel  # noqa: F401  (used by typing)

logger = logging.getLogger(__name__)


class ContrastiveTransitionTrainer:
    """Train TransitionModel with MSE + pairwise ranking loss."""

    def __init__(self, model,
                 lr: float = 1e-3, weight_decay: float = 1e-5,
                 epochs: int = 30, val_split: float = 0.1,
                 patience: int = 8, min_delta: float = 1e-4,
                 lambda_rank: float = 5.0, margin: float = 0.1,
                 n_pairs_per_state: int = 10, batch_size: int = 256,
                 pw_subsample: int = 100, device: str = "cpu",
                 restore_best: bool = True):
        self.model = model.to(device)
        self.device = device
        self.epochs = epochs
        self.val_split = val_split
        self.patience = patience
        self.min_delta = min_delta
        self.lambda_rank = lambda_rank
        self.margin = margin
        self.n_pairs_per_state = n_pairs_per_state
        self.batch_size = batch_size
        self.pw_subsample = pw_subsample
        self.restore_best = restore_best
        self.optimizer = torch.optim.Adam(model.parameters(), lr=lr,
                                          weight_decay=weight_decay)
        self.history = {
            "train_loss": [], "val_loss": [], "cosine_sim": [],
            "ranking_loss": [], "ranking_acc": [],
            "best_epoch": None, "best_val_loss": None,
        }

    def _prepare_regular(self, data: dict):
        n = len(data["actions"])
        idx = np.random.permutation(n)
        split = max(1, int(n * self.val_split))
        val_idx, train_idx = idx[:split], idx[split:]

        def to_tensors(indices):
            return (
                torch.tensor(data["block_features"][indices], device=self.device),
                torch.tensor(data["global_features"][indices], device=self.device),
                torch.tensor(data["actions"][indices], device=self.device),
                torch.tensor(data["rewards"][indices], device=self.device).unsqueeze(-1),
                torch.tensor(data["next_block_features"][indices], device=self.device),
                torch.tensor(data["next_global_features"][indices], device=self.device),
            )
        return to_tensors(train_idx), to_tensors(val_idx)

    def _prepare_pairwise(self, pairwise_data: dict):
        n = len(pairwise_data["states_bf"])
        idx = np.random.permutation(n)
        split = max(1, int(n * self.val_split))
        val_idx, train_idx = idx[:split], idx[split:]

        def to_tensors(indices):
            return {
                "bf":      torch.tensor(pairwise_data["states_bf"][indices], device=self.device),
                "gf":      torch.tensor(pairwise_data["states_gf"][indices], device=self.device),
                "actions": torch.tensor(pairwise_data["actions"][indices], device=self.device),
                "rewards": torch.tensor(pairwise_data["rewards"][indices], device=self.device),
            }
        return to_tensors(train_idx), to_tensors(val_idx)

    def _mse_loss(self, bf, gf, a, r, nbf, ngf):
        pred_nbf, pred_ngf, pred_r = self.model(bf, gf, a)
        l_block  = nn.functional.mse_loss(pred_nbf - bf, nbf - bf)
        l_global = nn.functional.mse_loss(pred_ngf - gf, ngf - gf)
        l_reward = nn.functional.mse_loss(pred_r, r)
        total = l_block + l_global + 0.1 * l_reward
        return total, (pred_nbf, pred_ngf, pred_r)

    def _ranking_loss(self, pw):
        bf = pw["bf"]
        gf = pw["gf"]
        actions = pw["actions"]
        rewards = pw["rewards"]
        N, N_A = actions.shape

        n_pairs = self.n_pairs_per_state
        pair_i = torch.randint(0, N_A, (N, n_pairs), device=self.device)
        pair_j = torch.randint(0, N_A, (N, n_pairs), device=self.device)
        flat_i = pair_i.reshape(-1)
        flat_j = pair_j.reshape(-1)
        state_idx = torch.arange(N, device=self.device).unsqueeze(1).expand(N, n_pairs).reshape(-1)

        bf_flat = bf[state_idx]
        gf_flat = gf[state_idx]
        act_i = actions[state_idx, flat_i]
        act_j = actions[state_idx, flat_j]
        r_true_i = rewards[state_idx, flat_i]
        r_true_j = rewards[state_idx, flat_j]

        _, _, pred_r_i = self.model(bf_flat, gf_flat, act_i)
        _, _, pred_r_j = self.model(bf_flat, gf_flat, act_j)
        pred_r_i = pred_r_i.squeeze(-1)
        pred_r_j = pred_r_j.squeeze(-1)

        target = torch.sign(r_true_i - r_true_j)
        nonzero = (target != 0)
        if nonzero.sum() == 0:
            return torch.tensor(0.0, device=self.device), 0.5
        pred_diff = pred_r_i - pred_r_j
        per_pair = torch.clamp(-target * pred_diff + self.margin, min=0)
        loss = per_pair[nonzero].mean()

        with torch.no_grad():
            pred_sign = torch.sign(pred_diff)
            correct = ((pred_sign == target) & nonzero).float().sum()
            total = nonzero.float().sum()
            acc = (correct / total).item()
        return loss, acc

    def _cosine_sim(self, pred, target):
        p = pred.reshape(pred.shape[0], -1)
        t = target.reshape(target.shape[0], -1)
        return nn.functional.cosine_similarity(p, t, dim=-1).mean().item()

    def train(self, data: dict, pairwise_data: dict) -> dict:
        train_mse, val_mse = self._prepare_regular(data)
        train_pw, val_pw = self._prepare_pairwise(pairwise_data)

        best_val_loss = float("inf")
        best_epoch = -1
        best_state = None
        wait = 0

        n_train = train_mse[0].shape[0]
        bs = self.batch_size

        for epoch in range(self.epochs):
            self.model.train()
            perm = torch.randperm(n_train, device=self.device)
            mse_losses = []
            for start in range(0, n_train, bs):
                idx = perm[start:start + bs]
                batch_mse = tuple(t[idx] for t in train_mse)

                self.optimizer.zero_grad()
                mse_loss, _ = self._mse_loss(*batch_mse)

                if self.lambda_rank > 0 and self.pw_subsample > 0:
                    n_pw = train_pw["bf"].shape[0]
                    sub = min(self.pw_subsample, n_pw)
                    pw_idx = torch.randperm(n_pw, device=self.device)[:sub]
                    sub_pw = {k: v[pw_idx] for k, v in train_pw.items()}
                    rank_loss, _ = self._ranking_loss(sub_pw)
                else:
                    rank_loss = torch.tensor(0.0, device=self.device)

                total_loss = mse_loss + self.lambda_rank * rank_loss
                total_loss.backward()
                self.optimizer.step()
                mse_losses.append(mse_loss.item())

            avg_mse = float(np.mean(mse_losses))
            self.history["train_loss"].append(avg_mse)

            self.model.eval()
            with torch.no_grad():
                v_mse, (v_nbf, v_ngf, _) = self._mse_loss(*val_mse)
                v_rank, v_acc = self._ranking_loss(val_pw)
                cos_b = self._cosine_sim(v_nbf, val_mse[4])
                cos_g = self._cosine_sim(v_ngf.unsqueeze(1), val_mse[5].unsqueeze(1))
            val_loss = v_mse.item() + self.lambda_rank * v_rank.item()
            self.history["val_loss"].append(val_loss)
            self.history["cosine_sim"].append((cos_b + cos_g) / 2)
            self.history["ranking_acc"].append(v_acc)
            self.history["ranking_loss"].append(v_rank.item())

            improved = val_loss < (best_val_loss - self.min_delta)
            if improved:
                best_val_loss = val_loss
                best_epoch = epoch + 1
                best_state = {k: v.detach().cpu().clone()
                              for k, v in self.model.state_dict().items()}
                wait = 0
            else:
                wait += 1

            if (epoch + 1) % 5 == 0 or epoch == 0:
                logger.info(
                    "Epoch %2d/%d  mse=%.5f  rank_val=%.5f  val=%.5f  cos=%.4f  rank_acc=%.3f",
                    epoch + 1, self.epochs, avg_mse, v_rank.item(),
                    val_loss, (cos_b + cos_g) / 2, v_acc,
                )

            if self.patience > 0 and wait >= self.patience:
                logger.info("Early stopping at epoch %d (best=%d)", epoch + 1, best_epoch)
                break

        self.history["best_epoch"] = best_epoch
        self.history["best_val_loss"] = float(best_val_loss)
        if self.restore_best and best_state is not None:
            self.model.load_state_dict(best_state)
        return self.history
