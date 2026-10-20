.PHONY: test demo

test:
	pytest -q

demo:
	python3 -m omniaudit scan examples/buggy_pkg --benchmark --output reports/latest_report.md
