"""Fine-tune (or train from scratch) a PhaseNet / EQTransformer picker on a SeisBench dataset.

Typical use: adapt pretrained weights to accelerometer records (HN channels), the instrument type
of the 20 Vietnamese stations, then compare before/after with evaluate_picker.py.

    python 511/finetune_picker.py --dataset InstanceGM --channels HN --weights instance \
        --epochs 20 --batch-size 256 --device cuda --out 511/outputs/finetune/instance_hn

    python 511/evaluate_picker.py --dataset InstanceGM --channels HN --split-mode event \
        --model phasenet --weights 511/outputs/finetune/instance_hn/best --device cuda

The split is event-grouped (``--split-mode event``) so no earthquake appears in both training and
test traces. The best model on the dev set is saved as <out>/best.{json,pt} (SeisBench format) and
loads anywhere a weights name is accepted (pick.py, evaluate_picker.py, e2e_run.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.data import apply_filters, load_dataset, phase_columns, split_dataset  # noqa: E402
from dl.pickers import load_picker  # noqa: E402


def make_generator(dataset, model, phase_dict, sigma, train=True):
    import seisbench.generate as sbg

    n_in = int(model.in_samples)
    aug = [
        # a window that contains at least one pick, then a random crop of the model's input length
        sbg.WindowAroundSample(list(phase_dict.keys()), samples_before=n_in, windowlen=2 * n_in,
                               selection="random" if train else "first", strategy="variable"),
        sbg.RandomWindow(windowlen=n_in, strategy="pad"),
        sbg.Normalize(demean_axis=-1, amp_norm_axis=-1, amp_norm_type=getattr(model, "norm", "peak")),
        sbg.ChangeDtype(np.float32),
        sbg.ProbabilisticLabeller(label_columns=phase_dict, model_labels=model.labels, sigma=sigma, dim=0),
    ]
    gen = sbg.GenericGenerator(dataset)
    gen.add_augmentations(aug)
    return gen


def loss_fn(y_pred, y_true, eps=1e-5):
    # cross entropy over the class axis, averaged over samples and batch (SeisBench PhaseNet recipe)
    import torch

    h = y_true * torch.log(y_pred + eps)
    return -h.mean(-1).sum(-1).mean()


def run_epoch(model, loader, optimizer, device, train=True, max_batches=None):
    import torch

    model.train(train)
    total, n = 0.0, 0
    for b, batch in enumerate(loader):
        if max_batches and b >= max_batches:
            break
        x = batch["X"].to(device)
        y = batch["y"].to(device)
        with torch.set_grad_enabled(train):
            pred = model(x)
            if isinstance(pred, (tuple, list)):  # EQTransformer returns (det, p, s)
                pred = torch.stack([pred[1], pred[2], 1 - pred[1] - pred[2]], dim=1)
            loss = loss_fn(pred, y)
            if train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
        total += loss.item() * len(x)
        n += len(x)
    return total / max(n, 1)


def main(argv=None):
    import torch
    from seisbench.util import worker_seeding
    from torch.utils.data import DataLoader

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True)
    p.add_argument("--model", default="phasenet", choices=["phasenet"])
    p.add_argument("--weights", default="instance", help="pretrained name, saved path, or 'none' to train from scratch")
    p.add_argument("--channels", nargs="*", help="instrument codes to keep, e.g. HN")
    p.add_argument("--split-mode", default="event", choices=["event", "dataset"])
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--sigma", type=int, default=20, help="label Gaussian width in samples")
    p.add_argument("--patience", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-train-batches", type=int, help="cap batches per epoch (quick runs)")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    torch.manual_seed(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = load_dataset(a.dataset, sampling_rate=100.0)
    apply_filters(ds, channels=a.channels)
    pdict = phase_columns(ds.metadata)
    if not pdict:
        raise SystemExit("dataset has no P/S arrival columns")
    has_pick = ds.metadata[list(pdict)].notna().any(axis=1).to_numpy()
    ds.filter(has_pick, inplace=True)
    splits = split_dataset(ds, mode=a.split_mode, seed=a.seed)
    print({k: len(v) for k, v in splits.items()}, "traces; phase columns:", pdict)

    model = load_picker(a.model, a.weights, a.device)
    gens = {k: make_generator(v, model, pdict, a.sigma, train=(k == "train")) for k, v in splits.items()}
    loaders = {k: DataLoader(g, batch_size=a.batch_size, shuffle=(k == "train"), num_workers=a.workers,
                             worker_init_fn=worker_seeding, drop_last=False) for k, g in gens.items() if len(g)}
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=max(1, a.patience // 2))

    history, best, wait = [], np.inf, 0
    dev_before = run_epoch(model, loaders["dev"], None, a.device, train=False) if "dev" in loaders else np.nan
    print(f"dev loss before training: {dev_before:.4f}")
    for epoch in range(1, a.epochs + 1):
        t0 = time.time()
        tr = run_epoch(model, loaders["train"], opt, a.device, train=True, max_batches=a.max_train_batches)
        dv = run_epoch(model, loaders["dev"], None, a.device, train=False) if "dev" in loaders else tr
        sched.step(dv)
        history.append({"epoch": epoch, "train_loss": tr, "dev_loss": dv, "lr": opt.param_groups[0]["lr"],
                        "seconds": time.time() - t0})
        print(f"epoch {epoch:3d}  train {tr:.4f}  dev {dv:.4f}  ({time.time() - t0:.0f} s)")
        if dv < best - 1e-5:
            best, wait = dv, 0
            model.save(str(out / "best"))
        else:
            wait += 1
            if wait >= a.patience:
                print("early stopping")
                break
    model.save(str(out / "last"))
    test = run_epoch(load_picker(a.model, str(out / "best"), a.device), loaders["test"], None, a.device,
                     train=False) if "test" in loaders and (out / "best.pt").exists() else np.nan
    info = {"args": vars(a), "dev_loss_before": dev_before, "best_dev_loss": best, "test_loss_best": test,
            "history": history, "splits": {k: len(v) for k, v in splits.items()}}
    (out / "training.json").write_text(json.dumps(info, indent=2, default=str))
    print(f"best dev loss {best:.4f} (before {dev_before:.4f}), test loss {test:.4f}; saved {out / 'best'}.{{json,pt}}")
    print(f"evaluate: python 511/evaluate_picker.py --dataset {a.dataset} --split-mode {a.split_mode} "
          f"--model {a.model} --weights {out / 'best'}" + (f" --channels {' '.join(a.channels)}" if a.channels else ""))


if __name__ == "__main__":
    main()
