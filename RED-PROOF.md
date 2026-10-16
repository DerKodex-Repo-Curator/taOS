RED-PROOF: Show the old-curl test FAILING on the BASE branch

```bash
$ python3 -m pytest -q tests/test_install_network_retries.py
FAILED tests/test_install_network_retries.py::test_curl_retry_without_retry_all_errors - ...
2 failed, 2 passed
```
