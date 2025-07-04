import sys
import importlib.util

# Import the module using the file path
spec = importlib.util.spec_from_file_location("version_stats", "../version-stats.py")
version_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version_stats)

# Get the MavenVersionChecker class
MavenVersionChecker = version_stats.MavenVersionChecker

# Create a test instance
checker = MavenVersionChecker()

# Test versions dictionary
versions = {
    "turbine": "0.12.1",
    "coil": "2.2.2"
}

# Test both formats
print("Testing module format:")
line1 = 'turbine = { module = "app.cash.turbine:turbine", version.ref = "turbine" }'
result1 = checker.parse_library_line(line1, versions)
print(f"Result: {result1}")

print("\nTesting group and name format:")
line2 = 'compose-coil = { group = "io.coil-kt", name = "coil-compose", version.ref = "coil"}'
result2 = checker.parse_library_line(line2, versions)
print(f"Result: {result2}")

print("\nTest completed.")
