"""
Encodes a file to base64 for pasting directly into a GitHub Actions
secret -- prints just the clean encoded string, no header/footer noise
(unlike certutil -encode, which adds lines you'd have to strip by hand).

    python auto-apply/encode_secret.py state/eeo_answers.json
"""
import base64
import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: python encode_secret.py <path-to-file>")
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")

    print(encoded)


if __name__ == "__main__":
    main()
