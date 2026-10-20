"""Kiểm thử property-based cho ParameterMapper sử dụng Hypothesis."""

import math
from pathlib import Path
import pytest
from hypothesis import given, strategies as st
from auto_sound.mixer.parameter_mapper import ParameterMapper, SubMapper

PROFILE_PATH = Path(__file__).resolve().parent.parent / "device_profiles" / "xr18.toml"


@pytest.fixture
def mapper() -> ParameterMapper:
    return ParameterMapper.from_profile(PROFILE_PATH)


class TestSubMapperProperties:
    """Kiểm thử các bất biến toán học của SubMapper."""

    @given(st.floats(min_value=-1000.0, max_value=50000.0, allow_nan=False, allow_infinity=False))
    def test_freq_to_float_bounds(self, val: float) -> None:
        sub = SubMapper(min_val=20.0, max_val=20000.0, steps=201, is_log=True)
        norm = sub.to_float(val)
        assert 0.0 <= norm <= 1.0

    @given(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    def test_gain_to_float_bounds(self, val: float) -> None:
        sub = SubMapper(min_val=-15.0, max_val=15.0, steps=121, is_log=False)
        norm = sub.to_float(val)
        assert 0.0 <= norm <= 1.0

    @given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    def test_from_float_bounds(self, norm: float) -> None:
        sub = SubMapper(min_val=20.0, max_val=20000.0, steps=201, is_log=True)
        val = sub.from_float(norm)
        assert 20.0 <= val <= 20000.0

    @given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    def test_quantize_float_idempotent(self, norm: float) -> None:
        sub = SubMapper(min_val=20.0, max_val=20000.0, steps=201, is_log=True)
        q1 = sub.quantize_float(norm)
        q2 = sub.quantize_float(q1)
        assert math.isclose(q1, q2, abs_tol=1e-9)

    @given(st.floats(min_value=20.0, max_value=20000.0, allow_nan=False, allow_infinity=False))
    def test_snap_idempotent(self, val: float) -> None:
        sub = SubMapper(min_val=20.0, max_val=20000.0, steps=201, is_log=True)
        s1 = sub.snap(val)
        s2 = sub.snap(s1)
        assert math.isclose(s1, s2, rel_tol=1e-7, abs_tol=1e-7)

    @given(st.integers(min_value=0, max_value=200))
    def test_exact_step_roundtrip(self, step_idx: int) -> None:
        sub = SubMapper(min_val=20.0, max_val=20000.0, steps=201, is_log=True)
        exact_float = step_idx / 200.0
        val = sub.from_float(exact_float)
        recalculated_float = sub.to_float(val)
        assert math.isclose(exact_float, recalculated_float, abs_tol=1e-7)


class TestParameterMapperXR18:
    """Kiểm thử ParameterMapper tích hợp với hồ sơ xr18.toml."""

    def test_load_from_profile(self, mapper: ParameterMapper) -> None:
        assert mapper.freq.min_val == 20.0
        assert mapper.freq.max_val == 20000.0
        assert mapper.gain.min_val == -15.0
        assert mapper.gain.max_val == 15.0
        assert mapper.q.min_val == 0.3
        assert mapper.q.max_val == 10.0

    def test_known_boundary_values(self, mapper: ParameterMapper) -> None:
        assert math.isclose(mapper.freq.to_float(20.0), 0.0, abs_tol=1e-7)
        assert math.isclose(mapper.freq.to_float(20000.0), 1.0, abs_tol=1e-7)
        assert math.isclose(mapper.gain.to_float(-15.0), 0.0, abs_tol=1e-7)
        assert math.isclose(mapper.gain.to_float(0.0), 0.5, abs_tol=1e-7)
        assert math.isclose(mapper.gain.to_float(15.0), 1.0, abs_tol=1e-7)
        assert math.isclose(mapper.q.to_float(0.3), 0.0, abs_tol=1e-7)
        assert math.isclose(mapper.q.to_float(10.0), 1.0, abs_tol=1e-7)
