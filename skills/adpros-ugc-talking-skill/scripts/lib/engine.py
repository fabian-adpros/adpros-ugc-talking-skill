"""Background engines. U2-Net stays the fallback when a heavier net is missing.

BiRefNet_lite (ZhengPeng7/BiRefNet_lite) is MIT code and MIT weights.
The author confirmed the checkpoints are MIT, and the model card says license: mit.
BEN2 base (PramaLLC/BEN2) is MIT code and MIT weights. The commercial refiner is
not this package. Neither weight file is committed here. They download on first use.
"""

from __future__ import annotations

ENGINES = ("birefnet", "ben2", "u2net", "apple-vision")
BIREFNET_ID = "ZhengPeng7/BiRefNet_lite"
# MIT model card commit. Pinned so the download does not float.
BIREFNET_REVISION = "aa62cd87eafb9cc43056d08ef3615a14628b831d"
BEN2_ID = "PramaLLC/BEN2"


def birefnet_available() -> bool:
    try:
        import einops  # noqa: F401
        import kornia  # noqa: F401
        import timm  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def ben2_available() -> bool:
    try:
        import ben2  # noqa: F401
    except Exception:
        return False
    return True


def u2net_python_available() -> bool:
    try:
        import torch  # noqa: F401
        from backgroundremover.u2net import detect  # noqa: F401
    except Exception:
        return False
    return True


def select_engine(requested: str, explicit: bool = False) -> tuple[str, str]:
    from .util import UGCError

    name = (requested or "birefnet").lower()
    if name not in ENGINES:
        raise UGCError(
            f"Unknown background engine {name}. Use birefnet, ben2, u2net, or apple-vision.",
            f"Motor de fondo desconocido {name}. Usa birefnet, ben2, u2net o apple-vision.",
        )
    if name == "apple-vision":
        from .applevision import supported

        if supported():
            return "apple-vision", ""
        if explicit:
            raise UGCError(
                "apple-vision only runs on macOS. It segments people, so a product in the hand can be erased.",
                "apple-vision solo corre en macOS. Separa personas, así que un producto en la mano puede desaparecer.",
            )
        return "birefnet", "apple-vision is macOS-only, so this run stayed on birefnet."
    if name == "birefnet":
        if birefnet_available():
            return "birefnet", ""
        if explicit:
            raise UGCError(
                "BiRefNet is not installed. Run ./install.sh --with-bg (transformers, timm, kornia).",
                "BiRefNet no está instalado. Corre ./install.sh --with-bg.",
            )
        return "u2net", "BiRefNet was not importable, so the matte used u2net."
    if name == "ben2":
        if ben2_available():
            return "ben2", ""
        if explicit:
            raise UGCError(
                "BEN2 is not installed. The MIT base is PramaLLC/BEN2: pip install the ben2 package.",
                "BEN2 no está instalado. La base MIT es PramaLLC/BEN2.",
            )
        return "u2net", "BEN2 was not importable, so the matte used u2net."
    return "u2net", ""


def pick_device():
    import os

    import torch

    # Some BiRefNet ops are missing on MPS. Falling back keeps the run alive.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        # fp32. fp16 on MPS hits unimplemented ops and the fallback is slower.
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


# Seconds per frame at short side 320, unless noted.
# birefnet CPU: 1.6 s/frame on one Mac after MPS crashed (1,270 frames, about 34 min).
#   An earlier CPU clip was about 1.05 s/frame (331 frames, about 6 min). The estimate uses 1.6.
# u2net CLI: about 72s for that 331-frame clip.
# apple-vision: 30 frames in 7s on that same Mac, about 0.24 s/frame, about 5 min for 1,270 frames.
CPU_SECONDS_PER_FRAME = {
    "birefnet": 1.6,
    "u2net": 72.0 / 331.0,
    "ben2": 1.2,
    "apple-vision": 0.24,
}
BG_COST_LIMIT_SECONDS = 180.0


def estimate_bg_seconds(engine: str, frames: int, device: str, infer_size: int) -> float | None:
    """CPU estimate scaled by resolution. MPS has no measurement, so it returns None."""
    if device == "mps":
        return None
    base = CPU_SECONDS_PER_FRAME.get(engine, CPU_SECONDS_PER_FRAME["birefnet"])
    scale = (max(64, int(infer_size)) / 320.0) ** 2
    if device == "cuda":
        scale *= 0.15
    return base * max(0, int(frames)) * scale


def bg_cost_should_stop(device: str, estimate_seconds: float | None, approved: bool) -> bool:
    if approved or estimate_seconds is None:
        return False
    return device == "cpu" and estimate_seconds > BG_COST_LIMIT_SECONDS


def mps_crash_action(estimate_seconds: float | None, approved: bool) -> str:
    """What to do after BiRefNet crashes on MPS.

    `checkpoint` asks the user before a long CPU run. `cpu` continues on CPU
    because they already accepted the wait, or the estimate is short.
    """
    if bg_cost_should_stop("cpu", estimate_seconds, approved):
        return "checkpoint"
    return "cpu"


def device_name() -> str:
    try:
        return str(pick_device())
    except Exception:
        return "cpu"


_MODELS: dict = {}


def predict_masks(frames, engine: str, model_name: str, device):
    """Return one uint8 mask per RGB frame. Frames are already at infer size."""
    if engine == "birefnet":
        return _birefnet_masks(frames, device)
    if engine == "ben2":
        return _ben2_masks(frames, device)
    return _u2net_masks(frames, model_name or "u2net", device)


def _quiet_hub() -> None:
    """The pinned BiRefNet repo is MIT and trusted. Hub login stays optional."""
    import logging
    import os
    import warnings

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    warnings.filterwarnings("ignore", message=".*trust_remote_code.*")
    warnings.filterwarnings("ignore", message=".*[Uu]nauthenticated.*")
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    try:
        from huggingface_hub.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
    except Exception:
        pass


def _birefnet_masks(frames, device):
    import os

    import numpy as np
    import torch
    from PIL import Image
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation

    key = ("birefnet", str(device))
    model = _MODELS.get(key)
    if model is None:
        _quiet_hub()
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        print(
            "bg: loading ZhengPeng7/BiRefNet_lite "
            f"revision {BIREFNET_REVISION[:12]} (MIT). "
            "That repo's code is trusted. Set HF_TOKEN if you want a higher Hub rate limit."
        )
        kwargs = {"revision": BIREFNET_REVISION, "trust_remote_code": True}
        if token:
            kwargs["token"] = token
        model = AutoModelForImageSegmentation.from_pretrained(BIREFNET_ID, **kwargs)
        # fp32. fp16 on MPS crashes or falls through on ops this model uses.
        model.float()
        model.to(device)
        model.eval()
        _MODELS[key] = model
    height, width = frames[0].shape[:2]
    transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ]
    )
    masks = []
    for frame in frames:
        # infer_size already chose this resolution. Do not force 1024.
        image = Image.fromarray(frame).resize((width, height))
        tensor = transform(image).unsqueeze(0).to(device)
        with torch.no_grad():
            pred = model(tensor)
            if isinstance(pred, (list, tuple)):
                pred = pred[-1]
            pred = pred.sigmoid()
            mask = pred[0, 0].detach().float().cpu().numpy()
        mask = np.clip(np.rint(mask * 255.0), 0, 255).astype(np.uint8)
        if mask.shape != (height, width):
            mask = np.array(Image.fromarray(mask).resize((width, height)))
        masks.append(mask)
    return masks


def _ben2_masks(frames, device):
    import numpy as np
    from ben2 import BEN_Base
    from PIL import Image

    key = ("ben2", str(device))
    model = _MODELS.get(key)
    if model is None:
        model = BEN_Base.from_pretrained(BEN2_ID)
        model.to(device)
        model.eval()
        _MODELS[key] = model
    height, width = frames[0].shape[:2]
    masks = []
    for frame in frames:
        image = Image.fromarray(frame).resize((width, height)).convert("RGB")
        foreground = model.inference(image, refine_foreground=False)
        alpha = foreground.split()[-1]
        mask = np.array(alpha.resize((width, height)))
        masks.append(mask.astype(np.uint8))
    return masks


def _u2net_masks(frames, model_name: str, device):
    import numpy as np
    import torch
    from backgroundremover.u2net import detect

    key = ("u2net", model_name, str(device))
    net = _MODELS.get(key)
    if net is None:
        net = detect.load_model(model_name=model_name)
        net.to(device)
        net.eval()
        _MODELS[key] = net
    masks = []
    for frame in frames:
        image = frame.astype(np.float32)
        peak = float(image.max()) or 1.0
        image = image / peak
        mean = (0.485, 0.456, 0.406)
        std = (0.229, 0.224, 0.225)
        for channel in range(3):
            image[:, :, channel] = (image[:, :, channel] - mean[channel]) / std[channel]
        tensor = torch.from_numpy(np.ascontiguousarray(image.transpose(2, 0, 1))).unsqueeze(0).to(device)
        with torch.no_grad():
            out = net(tensor)
            pred = out[0] if isinstance(out, (tuple, list)) else out
            pred = pred[:, 0]
            high = torch.max(pred)
            low = torch.min(pred)
            pred = (pred - low) / (high - low + 1e-8)
            masks.append((pred * 255).clamp(0, 255).to(torch.uint8).cpu().numpy()[0])
    return masks
