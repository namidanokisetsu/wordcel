"""Desktop and dictionary import commands; GUI dependencies stay lazy."""
import argparse
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "search":
        from wordcel.scripts.quick_lookup import main as search_main
        return search_main(argv[1:] if argv else [])
    parser = argparse.ArgumentParser(prog="wordcel", description="Multilingual OCR popup dictionary")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("search", help="Open the dictionary popup")
    importer = commands.add_parser("import-dictionaries", help="Add Yomitan dictionaries")
    importer.add_argument("dictionary_files", nargs="+")
    importer.add_argument("--language", help="Language for dictionaries without language metadata")
    importer.add_argument("--directory", help="Dictionary library directory")
    args = parser.parse_args(argv)
    if args.command == "import-dictionaries":
        from wordcel.dictionary.library import import_yomitan
        for filename in args.dictionary_files:
            print(import_yomitan(filename, args.directory, args.language, progress=print))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
