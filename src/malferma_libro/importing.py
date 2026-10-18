"""Import a cancellable batch while preserving exact paths for retry."""

from .tasks import TaskCancelled


def import_books(library, paths, token):
    """Return successful (record, book, duplicate) entries and (path, error).

    A failed book does not discard earlier imports. Cancellation stops the
    remaining batch; transactions already committed by the library remain.
    """
    paths = tuple(paths)
    known_ids = {record["id"] for record in library.books}
    imported, errors = [], []
    for index, path in enumerate(paths):
        token.check()
        token.progress(index, len(paths))
        try:
            record, book = library.import_book_with_content(path, cancel=token)
            imported.append((record, book, record["id"] in known_ids))
            known_ids.add(record["id"])
        except TaskCancelled:
            raise
        except Exception as error:
            errors.append((path, error))
        token.progress(index + 1, len(paths))
    return imported, errors
