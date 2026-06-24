"""Tool 3: Train contrastive ensemble + ONNX export.

Reads <prepared_dir>/tool2/{transitions,pairwise}.npz, trains N
TransitionModel members with the contrastive (MSE + ranking) loss,
exports each best ckpt to ONNX (n_blocks statically baked).

Output (under <prepared_dir>/tool3/):
    ensemble_memberN.onnx       (N members, default 3)
    ensemble_memberN.pt         (intermediate; not shipped)
    train_summary.json          (per-member best_val_loss, ranking_acc, ...)
    train.log

Reference config:
    n_members=3, lambda_rank=5.0, margin=0.1, epochs=30, patience=8,
    batch_size=256, val_split=0.1, n_pairs_per_state=10, pw_subsample=100

Runtime estimate (county, 2600 blocks, 6K transitions + 1000x50 pairwise):
    ~10-30 min per member CPU; 3 members ~= 30-90 min total.
Small region (30 blocks): ~1 min total.
"""
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import torch

logger = logging.getLogger(__name__)


def _set_seed(seed: int):
    np.random.seed(seed)
    torch.manual_seed(seed)


def _train_one_member(member_idx, transitions, pairwise, n_blocks, k_global,
                      n_actions, lambda_rank, margin, epochs, patience,
                      batch_size, n_pairs_per_state, pw_subsample,
                      lr, weight_decay, val_split, seed, device, say):
    """Train one ensemble member. Returns (model, history)."""
    try:
        from farmland_mpc.transition_model import TransitionModel
        from farmland_mpc.contrastive_trainer import ContrastiveTransitionTrainer
    except ImportError:
        from core.transition_model import TransitionModel
        from core.contrastive_trainer import ContrastiveTransitionTrainer

    say(f"  [member {member_idx}] seed={seed}, n_blocks={n_blocks}, "
        f"k_global={k_global}, n_actions={n_actions}")
    _set_seed(seed)

    model = TransitionModel(n_blocks=n_blocks, n_actions=n_actions,
                            k_global=k_global)
    n_params = sum(p.numel() for p in model.parameters())
    say(f"  [member {member_idx}] {n_params} parameters")

    trainer = ContrastiveTransitionTrainer(
        model, lr=lr, weight_decay=weight_decay,
        epochs=epochs, val_split=val_split,
        patience=patience, lambda_rank=lambda_rank, margin=margin,
        n_pairs_per_state=n_pairs_per_state, batch_size=batch_size,
        pw_subsample=pw_subsample, device=device, restore_best=True,
    )
    t0 = time.time()
    history = trainer.train(transitions, pairwise)
    elapsed = time.time() - t0
    say(f"  [member {member_idx}] trained in {elapsed:.1f}s, "
        f"best_epoch={history['best_epoch']}, "
        f"best_val_loss={history['best_val_loss']:.5f}, "
        f"final cos_sim={history['cosine_sim'][-1]:.4f}, "
        f"ranking_acc={history['ranking_acc'][-1]:.3f}")
    return model, history, elapsed


def _export_onnx(model, n_blocks, k_global, onnx_path, say):
    """torch.onnx.export with batch dynamic, n_blocks static."""
    import io
    model.eval()
    B = 2
    dummy = (
        torch.randn(B, n_blocks, 17),
        torch.randn(B, k_global),
        torch.randint(0, n_blocks, (B,), dtype=torch.long),
    )
    # PyTorch 2.10+ prints emoji (✅) during export which crashes on GBK consoles.
    # Redirect stdout to suppress.
    _orig_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        torch.onnx.export(
            model, dummy, str(onnx_path),
            input_names=["block_features", "global_features", "action"],
            output_names=["next_block", "next_global", "reward"],
            dynamic_axes={
                "block_features":  {0: "batch"},
                "global_features": {0: "batch"},
                "action":          {0: "batch"},
                "next_block":      {0: "batch"},
                "next_global":     {0: "batch"},
                "reward":          {0: "batch"},
            },
            opset_version=17,
        )
    finally:
        sys.stdout = _orig_stdout

    # Parity check
    with torch.no_grad():
        t_out = model(*dummy)
    import onnxruntime as ort
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    o_out = sess.run(None, {
        "block_features":  dummy[0].numpy(),
        "global_features": dummy[1].numpy(),
        "action":          dummy[2].numpy(),
    })
    diffs = [float(np.abs(t.numpy() - o).max()) for t, o in zip(t_out, o_out)]
    worst = max(diffs)
    say(f"    onnx parity max diff = {worst:.2e}")
    assert worst < 1e-4, f"ONNX parity check failed: {worst}"


def run(prepared_dir: str,
        n_members: int = 3,
        epochs: int = 30,
        patience: int = 8,
        lambda_rank: float = 5.0,
        margin: float = 0.1,
        batch_size: int = 256,
        n_pairs_per_state: int = 10,
        pw_subsample: int = 100,
        lr: float = 1e-3,
        weight_decay: float = 1e-5,
        val_split: float = 0.1,
        seed_base: int = 0,
        torch_threads: int = 0,
        out_subdir: str = "tool3",
        messages=None):
    """Train ensemble + export ONNX. See module docstring for output layout.

    Parameters
    ----------
    prepared_dir : str
        Output of Tool 1 + Tool 2 (must contain tool2/transitions.npz +
        tool2/pairwise.npz).
    n_members : int
        Ensemble size (Paper 9 default 3).
    epochs, patience : int
        Per-member training caps.
    lambda_rank : float
        Weight on contrastive ranking loss. 0 = pure MSE; 5.0 = Paper 9 v6.
    margin : float
        Margin for ranking hinge loss.
    batch_size, n_pairs_per_state, pw_subsample : int
        Mini-batch and pairwise sampling controls.
    lr, weight_decay, val_split : float
    seed_base : int
        Member i uses seed = seed_base + i*1000.
    torch_threads : int
        torch.set_num_threads. 0 = leave default. On this machine 12 was
        observed best (>12 oversubscribes alongside ArcGIS Pro).
    messages : arcpy messages or None.
    """
    def _say(msg, level="info"):
        if messages is not None:
            getattr(messages, "addMessage" if level == "info"
                    else "addWarningMessage")(msg)
        logger.info(msg)
        print(msg, flush=True)

    prepared_dir = Path(prepared_dir)
    out_dir = prepared_dir / out_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    log_path = out_dir / "train.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)

    try:
        # Make sure core/ is importable
        toolbox_dir = str(Path(__file__).resolve().parent.parent)
        if toolbox_dir not in sys.path:
            sys.path.insert(0, toolbox_dir)

        if torch_threads > 0:
            torch.set_num_threads(torch_threads)
            _say(f"[Tool 3] torch.set_num_threads({torch_threads})")

        # Load tool2 outputs
        tool2_dir = prepared_dir / "tool2"
        tr_path = tool2_dir / "transitions.npz"
        pw_path = tool2_dir / "pairwise.npz"
        if not tr_path.exists():
            raise FileNotFoundError(
                f"{tr_path} missing. Run Tool 2 first."
            )
        if not pw_path.exists():
            raise FileNotFoundError(
                f"{pw_path} missing. Run Tool 2 first."
            )

        _say(f"[Tool 3] Loading {tr_path}")
        tr_npz = np.load(tr_path)
        transitions = {k: tr_npz[k] for k in tr_npz.files}
        _say(f"  transitions: {len(transitions['actions'])} rows, "
             f"block_features shape {transitions['block_features'].shape}")

        _say(f"[Tool 3] Loading {pw_path}")
        pw_npz = np.load(pw_path)
        pairwise = {k: pw_npz[k] for k in pw_npz.files}
        _say(f"  pairwise: {len(pairwise['states_bf'])} states x "
             f"{pairwise['actions'].shape[1]} actions")

        # Infer dimensions
        n_blocks = int(transitions["block_features"].shape[1])
        k_block = int(transitions["block_features"].shape[2])
        k_global = int(transitions["global_features"].shape[1])
        if k_block != 17:
            raise RuntimeError(
                f"K_BLOCK mismatch: data has {k_block}, vendored "
                "TransitionModel hardcodes 17. Re-run Tool 2 against the "
                "current env."
            )
        # n_actions = n_blocks (CountyLevelEnv.action_space = Discrete(n_blocks))
        n_actions = n_blocks

        _say(f"[Tool 3] Inferred dims: n_blocks={n_blocks}, "
             f"k_global={k_global}, n_actions={n_actions}")

        summary = {
            "config": {
                "prepared_dir": str(prepared_dir),
                "n_members": n_members, "epochs": epochs,
                "patience": patience, "lambda_rank": lambda_rank,
                "margin": margin, "batch_size": batch_size,
                "n_pairs_per_state": n_pairs_per_state,
                "pw_subsample": pw_subsample,
                "lr": lr, "weight_decay": weight_decay,
                "val_split": val_split, "seed_base": seed_base,
                "torch_threads": torch_threads,
                "n_blocks": n_blocks, "k_global": k_global,
            },
            "members": [],
        }

        t_total = time.time()
        for i in range(n_members):
            seed = seed_base + i * 1000
            _say(f"\n[Tool 3] === Training member {i + 1}/{n_members} ===")
            model, history, elapsed = _train_one_member(
                member_idx=i, transitions=transitions, pairwise=pairwise,
                n_blocks=n_blocks, k_global=k_global, n_actions=n_actions,
                lambda_rank=lambda_rank, margin=margin,
                epochs=epochs, patience=patience,
                batch_size=batch_size,
                n_pairs_per_state=n_pairs_per_state,
                pw_subsample=pw_subsample,
                lr=lr, weight_decay=weight_decay, val_split=val_split,
                seed=seed, device="cpu", say=_say,
            )

            # Save .pt (intermediate; not shipped to users)
            pt_path = out_dir / f"ensemble_member{i}.pt"
            torch.save(model.state_dict(), pt_path)

            # Export ONNX
            onnx_path = out_dir / f"ensemble_member{i}.onnx"
            _export_onnx(model, n_blocks, k_global, onnx_path, _say)
            onnx_size_kb = onnx_path.stat().st_size / 1024
            _say(f"  [member {i}] -> {onnx_path.name} ({onnx_size_kb:.1f} KB)")

            summary["members"].append({
                "index": i, "seed": seed,
                "elapsed_s": round(elapsed, 1),
                "best_epoch": history["best_epoch"],
                "best_val_loss": round(history["best_val_loss"], 6),
                "final_cosine_sim": round(history["cosine_sim"][-1], 6),
                "final_ranking_acc": round(history["ranking_acc"][-1], 4),
                "onnx": str(onnx_path),
                "pt": str(pt_path),
            })

        summary["total_elapsed_s"] = round(time.time() - t_total, 1)

        summary_path = out_dir / "train_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        _say(f"\n[Tool 3] All {n_members} members done in "
             f"{summary['total_elapsed_s']}s. Summary -> {summary_path}")
        return summary
    finally:
        logging.getLogger().removeHandler(fh)
        fh.close()
