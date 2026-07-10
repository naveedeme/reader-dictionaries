# Security policy

Do not report secrets, malicious dictionary archives, path traversal issues, checksum bypasses, or unsafe XML handling in a public issue. Use GitHub's private vulnerability reporting feature for this repository.

Dictionary packages are treated as untrusted input by the validator. The Android app must still verify the catalog checksum before extraction, reject absolute or parent-relative ZIP paths, validate the manifest, and open the database read-only before activation.
