from pathlib import Path
import runpy

target = Path(__file__).with_name("\u673a\u5668\u4eba\u63a7\u5236\u53f0.pyw")
runpy.run_path(str(target), run_name="__main__")
