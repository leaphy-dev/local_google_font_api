from pathlib import Path


def find_files_by_extension(directory, extensions):
    path = Path(directory)
    extensions = [ext.lower() for ext in extensions]
    for file in path.rglob('*'):
        file: Path
        if file.suffix.lower().strip(".") in extensions:
            yield file