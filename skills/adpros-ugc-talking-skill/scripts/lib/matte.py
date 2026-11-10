"""Matte cleanup that does not need torch.

`smooth_alpha` is the temporal median (or EMA) applied to the U2-Net masks.
A one-frame dropout in a solid product box is filled. The video path uses the
same rules; numpy is used there when torch is installed.
"""

from __future__ import annotations


def working_size(width: int, height: int, short: int) -> tuple[int, int]:
    """Aspect-preserving size whose short side is `short`, both multiples of 32.

    backgroundremover's video path resizes the height to 320 and then squares
    the frame to 320x320. A 9:16 frame becomes about 180x320 before that squash.
    This size keeps the aspect ratio instead.
    """
    short = max(64, min(1024, int(short)))
    short = max(32, (short // 32) * 32)
    if width <= 0 or height <= 0:
        return short, short
    if width <= height:
        out_w = short
        out_h = int(round(height * short / float(width)))
    else:
        out_h = short
        out_w = int(round(width * short / float(height)))
    out_w = max(32, int(round(out_w / 32.0)) * 32)
    out_h = max(32, int(round(out_h / 32.0)) * 32)
    return out_w, out_h


def smooth_alpha(frames, window: int = 3, mode: str = "median"):
    """Temporal smooth. `frames[t][y][x]` is 0..255. `window` 0 or 1 is a copy.

    An ndarray is checked before any truth test. NumPy raises on `if not array`.
    """
    from .util import UGCError

    array = None
    try:
        import numpy as np

        if isinstance(frames, np.ndarray):
            array = frames
    except ImportError:
        np = None
    try:
        if array is not None:
            if array.size == 0 or array.shape[0] == 0:
                return array
            return _smooth_np(array, window, mode)
        if not frames:
            return []
        return _smooth_list(frames, window, mode)
    except UGCError:
        raise
    except Exception as exc:
        raise UGCError(
            f"Matte smoothing failed ({exc}). Re-run with --bg-smooth 0 to skip it.",
            f"Falló el suavizado del mate ({exc}). Vuelve a correr con --bg-smooth 0.",
        ) from exc


def _smooth_list(frames: list, window: int, mode: str) -> list:
    window = int(window or 0)
    if window <= 1 or len(frames) < 2:
        return [[row[:] for row in frame] for frame in frames]
    if window % 2 == 0:
        window += 1
    if mode == "ema":
        return _ema(frames, window)
    return _median(frames, window)


def _median(frames: list, window: int) -> list:
    radius = window // 2
    height = len(frames[0])
    width = len(frames[0][0])
    out = []
    for time_index in range(len(frames)):
        start = max(0, time_index - radius)
        end = min(len(frames), time_index + radius + 1)
        frame = []
        for y in range(height):
            row = []
            for x in range(width):
                values = sorted(frames[moment][y][x] for moment in range(start, end))
                row.append(int(values[len(values) // 2]))
            frame.append(row)
        out.append(frame)
    return out


def _ema(frames: list, window: int) -> list:
    decay = 2.0 / (window + 1.0)
    height = len(frames[0])
    width = len(frames[0][0])
    previous = None
    out = []
    for frame in frames:
        if previous is None:
            previous = [row[:] for row in frame]
        else:
            nxt = []
            for y in range(height):
                nxt.append(
                    [
                        int(round(decay * frame[y][x] + (1.0 - decay) * previous[y][x]))
                        for x in range(width)
                    ]
                )
            previous = nxt
        out.append([row[:] for row in previous])
    return out


def morph_close(frame: list, radius: int = 1) -> list:
    """Fill small holes in a solid mask. Dilate, then erode."""
    radius = int(radius or 0)
    if radius <= 0:
        return [row[:] for row in frame]
    return _erode(_dilate(frame, radius), radius)


def _dilate(frame: list, radius: int) -> list:
    return _neighbor(frame, radius, max)


def _erode(frame: list, radius: int) -> list:
    return _neighbor(frame, radius, min)


def _neighbor(frame: list, radius: int, pick) -> list:
    height = len(frame)
    width = len(frame[0])
    out = []
    for y in range(height):
        row = []
        for x in range(width):
            values = []
            for dy in range(-radius, radius + 1):
                yy = min(height - 1, max(0, y + dy))
                for dx in range(-radius, radius + 1):
                    xx = min(width - 1, max(0, x + dx))
                    values.append(frame[yy][xx])
            row.append(int(pick(values)))
        out.append(row)
    return out


def _smooth_np(frames, window: int, mode: str):
    import numpy as np

    volume = np.asarray(frames)
    window = int(window or 0)
    if window <= 1 or volume.shape[0] < 2:
        return volume
    if window % 2 == 0:
        window += 1
    if mode == "ema":
        decay = 2.0 / (window + 1.0)
        out = np.empty_like(volume)
        previous = volume[0].astype(np.float32)
        out[0] = volume[0]
        for index in range(1, volume.shape[0]):
            previous = decay * volume[index].astype(np.float32) + (1.0 - decay) * previous
            out[index] = np.clip(np.rint(previous), 0, 255).astype(volume.dtype)
        return out
    radius = window // 2
    out = np.empty_like(volume)
    for index in range(volume.shape[0]):
        start = max(0, index - radius)
        end = min(volume.shape[0], index + radius + 1)
        # Same pick as the list path: sorted[len//2], not the average of an even window.
        ordered = np.sort(volume[start:end], axis=0)
        out[index] = ordered[(end - start) // 2]
    return out
