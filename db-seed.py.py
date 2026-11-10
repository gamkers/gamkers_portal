import subprocess
import sys

try:
    result = subprocess.run(
        ["flask", "--app", "wsgi", "db", "upgrade"],
        check=True,
        capture_output=True,
        text=True
    )

    print("Database migration completed successfully!")
    print(result.stdout)

except subprocess.CalledProcessError as e:
    print("Database migration failed!")
    print("Error:", e.stderr)
    sys.exit(1)

except FileNotFoundError:
    print("Flask command not found. Check your Python environment.")
    sys.exit(1)