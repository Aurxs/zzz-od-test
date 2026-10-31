"""显式开启的 Mac OCR 原生内存回归；新进程、固定形状、持续变化的内容。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def probe_detector_memory() -> dict[str, object]:
    """只跑 CPU 检测模型，防止有限输入重放掩盖按内容增长的原生缓存。"""
    import numpy as np

    from onnxocr.inference_engine import create_session
    from zzz_od.macos.memory_monitor import MacProcessMemoryReader

    model = Path('assets/models/onnx_ocr/ppocrv6/det.onnx')
    session = create_session(str(model), use_gpu=False)
    reader = MacProcessMemoryReader()
    generator = np.random.default_rng(20261030)
    image = np.empty((1, 3, 640, 640), dtype=np.float32)
    input_name = session.get_inputs()[0].name
    samples: list[int] = []
    for _ in range(28):
        generator.random(image.shape, dtype=np.float32, out=image)
        outputs = session.run(None, {input_name: image})
        assert all(np.isfinite(output).all() for output in outputs)
        del outputs
        sample = reader.read(os.getpid())['footprint_bytes']
        samples.append(sample)
        if sample > 2 * 1024**3:
            break
    return {'samples': samples, 'shape': list(image.shape)}


@pytest.mark.skipif(
    sys.platform != 'darwin' or os.environ.get('ZZZ_OD_TEST_NATIVE_MEMORY') != '1',
    reason='仅在设备空闲时显式开启，不与 GUI 或其他模型验证并行',
)
def test_fixed_shape_detector_does_not_cache_each_input() -> None:
    """预热后 24 个新内容输入应复用缓存，而不是逐输入保留原生缓冲。"""
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), '--probe'],
        capture_output=True, text=True, timeout=60, check=True,
    )
    result = json.loads(completed.stdout.split('MEMORY_RESULT=', 1)[1])
    samples = result['samples']
    assert len(samples) == 28, result
    assert max(samples[4:]) - samples[3] < 128 * 1024**2, result


if __name__ == '__main__' and sys.argv[1:] == ['--probe']:
    print(f'MEMORY_RESULT={json.dumps(probe_detector_memory())}', flush=True)
