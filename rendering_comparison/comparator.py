"""Compare two mode renders and compute diff scores."""

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import config
from .collector import PageMetrics


@dataclass
class ComparisonResult:
    host: str
    url: str
    rank: int
    pair_label: str = ""          # e.g. "headless_vs_headful"
    mode_a_name: str = ""         # e.g. "headless"
    mode_b_name: str = ""         # e.g. "headful"
    # Flags
    has_screenshot_diff: bool = False
    has_dom_count_diff: bool = False
    has_content_length_diff: bool = False
    has_structural_diff: bool = False
    has_title_diff: bool = False
    has_redirect_diff: bool = False
    # Numeric diffs
    screenshot_diff_pct: float = 0.0
    dom_count_ratio: float = 0.0
    content_length_ratio: float = 0.0
    network_request_diff: int = 0
    # Per-tag element count diffs: tag -> (mode_a_count, mode_b_count)
    tag_count_diffs: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Request type diffs: type -> (mode_a_count, mode_b_count)
    request_type_diffs: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Structural elements only in one mode
    elements_only_mode_b: list[str] = field(default_factory=list)
    elements_only_mode_a: list[str] = field(default_factory=list)
    # Console errors
    mode_a_console_errors: int = 0
    mode_b_console_errors: int = 0
    # Severity score
    severity: float = 0.0
    # Errors
    mode_a_error: str = ""
    mode_b_error: str = ""
    # Category
    diff_type: str = ""


def compute_screenshot_diff(path_a: Path, path_b: Path) -> float:
    """Return fraction of pixels that differ between two screenshots."""
    try:
        img_a = np.array(Image.open(path_a).convert("RGB"), dtype=np.int16)
        img_b = np.array(Image.open(path_b).convert("RGB"), dtype=np.int16)

        h = min(img_a.shape[0], img_b.shape[0])
        w = min(img_a.shape[1], img_b.shape[1])
        img_a = img_a[:h, :w]
        img_b = img_b[:h, :w]

        diff = np.abs(img_a - img_b)
        pixel_diff = np.any(diff > 25, axis=2)
        return float(pixel_diff.sum()) / float(pixel_diff.size)
    except Exception:
        return 0.0


def generate_diff_image(path_a: Path, path_b: Path, output_path: Path) -> None:
    """Create a visual diff image highlighting changed pixels in red."""
    try:
        img_a = np.array(Image.open(path_a).convert("RGB"), dtype=np.int16)
        img_b = np.array(Image.open(path_b).convert("RGB"), dtype=np.int16)

        h = min(img_a.shape[0], img_b.shape[0])
        w = min(img_a.shape[1], img_b.shape[1])
        img_a = img_a[:h, :w]
        img_b = img_b[:h, :w]

        diff = np.abs(img_a - img_b)
        changed = np.any(diff > 25, axis=2)

        result = img_b.copy().astype(np.uint8)
        result[changed] = [255, 0, 0]

        Image.fromarray(result).save(output_path)
    except Exception:
        pass


def _diff_dicts(
    a: dict[str, int], b: dict[str, int]
) -> dict[str, tuple[int, int]]:
    """Return keys where values differ, with (a, b) counts."""
    all_keys = set(a) | set(b)
    diffs: dict[str, tuple[int, int]] = {}
    for key in sorted(all_keys):
        a_val = a.get(key, 0)
        b_val = b.get(key, 0)
        if a_val != b_val:
            diffs[key] = (a_val, b_val)
    return diffs


def compare(
    mode_a: PageMetrics,
    mode_b: PageMetrics,
    host: str,
    rank: int,
    screenshots_dir: Path,
    mode_a_name: str = "",
    mode_b_name: str = "",
) -> ComparisonResult:
    """Compare two PageMetrics and produce a ComparisonResult."""
    a_name = mode_a_name or mode_a.mode
    b_name = mode_b_name or mode_b.mode
    pair_label = f"{a_name}_vs_{b_name}"

    result = ComparisonResult(
        host=host, url=mode_a.url, rank=rank,
        pair_label=pair_label, mode_a_name=a_name, mode_b_name=b_name,
    )
    result.mode_a_error = mode_a.error
    result.mode_b_error = mode_b.error

    if mode_a.error and mode_b.error:
        result.diff_type = "both_errored"
        return result
    if mode_a.error:
        result.diff_type = f"{a_name}_errored"
        result.severity = 100.0
        return result
    if mode_b.error:
        result.diff_type = f"{b_name}_errored"
        result.severity = 100.0
        return result

    # Screenshot diff
    a_ss = screenshots_dir / mode_a.screenshot_path
    b_ss = screenshots_dir / mode_b.screenshot_path
    if a_ss.exists() and b_ss.exists():
        result.screenshot_diff_pct = compute_screenshot_diff(a_ss, b_ss)
        result.has_screenshot_diff = (
            result.screenshot_diff_pct > config.SCREENSHOT_DIFF_THRESHOLD
        )
        if result.has_screenshot_diff:
            slug = host.replace(".", "_")
            generate_diff_image(a_ss, b_ss, screenshots_dir / f"{slug}_{pair_label}_diff.png")

    # DOM element count ratio (log2)
    if mode_a.dom_element_count > 0 and mode_b.dom_element_count > 0:
        result.dom_count_ratio = math.log2(
            mode_b.dom_element_count / mode_a.dom_element_count
        )
        result.has_dom_count_diff = abs(result.dom_count_ratio) > math.log2(
            1 + config.DOM_COUNT_RATIO_THRESHOLD
        )

    # Content length ratio (log2)
    if mode_a.visible_text_length > 0 and mode_b.visible_text_length > 0:
        result.content_length_ratio = math.log2(
            mode_b.visible_text_length / mode_a.visible_text_length
        )
        result.has_content_length_diff = abs(result.content_length_ratio) > math.log2(
            1 + config.CONTENT_LENGTH_RATIO_THRESHOLD
        )

    # Per-tag element count diffs
    result.tag_count_diffs = _diff_dicts(mode_a.tag_counts, mode_b.tag_counts)

    # Request type diffs
    result.request_type_diffs = _diff_dicts(
        mode_a.request_counts_by_type, mode_b.request_counts_by_type
    )

    # Network request total diff
    result.network_request_diff = (
        mode_b.network_request_count - mode_a.network_request_count
    )

    # Structural elements
    a_struct = mode_a.structural_present
    b_struct = mode_b.structural_present
    all_structural = set(a_struct) | set(b_struct)
    for el in sorted(all_structural):
        a_has = a_struct.get(el, False)
        b_has = b_struct.get(el, False)
        if b_has and not a_has:
            result.elements_only_mode_b.append(el)
        if a_has and not b_has:
            result.elements_only_mode_a.append(el)
    result.has_structural_diff = bool(
        result.elements_only_mode_b or result.elements_only_mode_a
    )

    # Title diff
    result.has_title_diff = mode_a.page_title != mode_b.page_title

    # Redirect diff
    result.has_redirect_diff = mode_a.final_url != mode_b.final_url

    # Console errors
    result.mode_a_console_errors = len(mode_a.console_errors)
    result.mode_b_console_errors = len(mode_b.console_errors)

    # Composite severity score
    tag_diff_magnitude = sum(
        abs(b - a) for a, b in result.tag_count_diffs.values()
    )
    req_diff_magnitude = sum(
        abs(b - a) for a, b in result.request_type_diffs.values()
    )

    result.severity = (
        30 * result.screenshot_diff_pct
        + 20 * min(abs(result.dom_count_ratio), 5.0)
        + 15 * min(abs(result.content_length_ratio), 5.0)
        + 10 * (1 if result.has_structural_diff else 0)
        + 5 * (1 if result.has_title_diff else 0)
        + 5 * (1 if result.has_redirect_diff else 0)
        + 5 * min(tag_diff_magnitude / 100, 5.0)
        + 5 * min(req_diff_magnitude / 20, 5.0)
    )

    # Categorize
    if result.has_redirect_diff:
        result.diff_type = "redirect_diff"
    elif result.has_dom_count_diff and result.has_screenshot_diff:
        result.diff_type = "missing_content"
    elif result.has_screenshot_diff:
        result.diff_type = "layout_diff"
    elif result.has_dom_count_diff:
        result.diff_type = "dom_diff"
    elif result.has_structural_diff:
        result.diff_type = "structural_diff"
    elif result.has_title_diff:
        result.diff_type = "title_diff"
    else:
        result.diff_type = "identical"

    return result
