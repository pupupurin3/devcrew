def parse_line(line):
    """Split one CSV line into a list of fields."""
    return [field.strip() for field in line.split(",")]
