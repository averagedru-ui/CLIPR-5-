"""M1: probe + frame-accurate seeking + VFR handling."""
from __future__ import annotations

import numpy as np

from vcomp.media.decoder import VideoDecoder
from vcomp.media.probe import probe


def test_probe_cfr(cfr_clip):
    info = probe(cfr_clip)
    assert (info.width, info.height) == (320, 180)
    assert abs(info.fps - 30.0) < 0.01
    assert 2.9 < info.duration < 3.2
    assert info.has_audio is True
    assert info.is_vfr is False


def test_seek_is_position_independent(cfr_clip):
    """A frame fetched cold (after a seek) matches the same frame reached by
    playing forward — i.e. seeking is frame-accurate, not off-by-one."""
    with VideoDecoder(cfr_clip, cache_size=4) as d:
        forward = [d.frame_at(i / d.fps) for i in range(20)]
        target = forward[15]

        d.clear_cache()
        d._last_decoded_pts = None  # force a real seek
        jumped = d.frame_at(15 / d.fps)

    assert jumped.shape == target.shape
    assert np.array_equal(jumped, target)


def test_random_access_roundtrip(cfr_clip):
    with VideoDecoder(cfr_clip) as d:
        a = d.frame_by_index(50)
        _ = d.frame_by_index(5)
        b = d.frame_by_index(50)
    assert np.array_equal(a, b)


def test_clamps_past_end(cfr_clip):
    with VideoDecoder(cfr_clip) as d:
        far = d.frame_at(999.0)
    assert far.shape[2] == 3


def test_vfr_resolves_by_time(vfr_clip):
    info = probe(vfr_clip)
    assert info.is_vfr is True
    with VideoDecoder(vfr_clip) as d:
        t_mid = info.duration / 2
        f1 = d.frame_at(t_mid)
        f2 = d.frame_at(t_mid)
    assert np.array_equal(f1, f2)


def test_lru_cache_bound(cfr_clip):
    with VideoDecoder(cfr_clip, cache_size=8) as d:
        for i in range(40):
            d.frame_by_index(i)
        assert len(d.cached_indices()) <= 8
