"""Vendored TransitionModel (Paper 9's 237K-param world model).

Source: D:/adk/data_agent/transition_model.py::TransitionModel.
Stripped of gymnasium dependency: this file contains ONLY the nn.Module.
The trainer + env wrappers stay in adk; this is the minimum surface needed
for Tool 3 training and ONNX export.

Architecture (kept identical to Paper 9 v6 ckpt):
    block encoder:   17 -> 64 -> 32        (per-block, shared)
    action embedding: Embed(n_actions, 32)
    global encoder:  K_GLOBAL -> 64 -> 32
    context (128D):  [selected_block_enc, action_emb, global_enc, mean_pool]
    block_delta:     128 -> 256 -> 256 -> K_BLOCK
    global_delta:    128 -> 256 -> K_GLOBAL
    reward:          128 -> 64 -> 1

Residual: only the selected block's features change per step.
"""
from typing import Optional, Tuple

import torch
import torch.nn as nn

K_BLOCK = 17

# Backward-compat default (Paper 9 county env). When training a new region,
# K_GLOBAL is inferred from the data and overrides this.
K_GLOBAL_DEFAULT = 12


class TransitionModel(nn.Module):
    def __init__(self, n_blocks: int, n_actions: Optional[int] = None,
                 k_global: int = K_GLOBAL_DEFAULT):
        super().__init__()
        self.n_blocks = n_blocks
        self.n_actions = n_actions or n_blocks
        self.k_global = k_global

        self.block_enc = nn.Sequential(
            nn.Linear(K_BLOCK, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
        )
        self.action_emb = nn.Embedding(self.n_actions, 32)
        self.global_enc = nn.Sequential(
            nn.Linear(k_global, 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(),
        )
        ctx_dim = 32 + 32 + 32 + 32  # = 128
        self.block_delta_head = nn.Sequential(
            nn.Linear(ctx_dim, 256), nn.ReLU(),
            nn.Linear(256, 256), nn.ReLU(),
            nn.Linear(256, K_BLOCK),
        )
        self.global_delta_head = nn.Sequential(
            nn.Linear(ctx_dim, 256), nn.ReLU(),
            nn.Linear(256, k_global),
        )
        self.reward_head = nn.Sequential(
            nn.Linear(ctx_dim, 64), nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, block_features: torch.Tensor,
                global_features: torch.Tensor,
                action: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        B = block_features.shape[0]

        all_enc = self.block_enc(block_features)        # (B, n_blocks, 32)
        mean_pool = all_enc.mean(dim=1)                  # (B, 32)

        idx = action.long().unsqueeze(-1).unsqueeze(-1).expand(B, 1, 32)
        selected_enc = all_enc.gather(1, idx).squeeze(1)  # (B, 32)

        act_emb = self.action_emb(action.long())          # (B, 32)
        glb_enc = self.global_enc(global_features)        # (B, 32)

        ctx = torch.cat([selected_enc, act_emb, glb_enc, mean_pool], dim=-1)

        b_delta = self.block_delta_head(ctx)              # (B, K_BLOCK)
        g_delta = self.global_delta_head(ctx)             # (B, K_GLOBAL)
        reward = self.reward_head(ctx)                    # (B, 1)

        next_block = block_features.clone()
        action_idx = action.long().unsqueeze(-1).unsqueeze(-1).expand(B, 1, K_BLOCK)
        selected_block = next_block.gather(1, action_idx)
        updated = selected_block + b_delta.unsqueeze(1)
        next_block.scatter_(1, action_idx, updated)

        next_global = global_features + g_delta
        return next_block, next_global, reward
