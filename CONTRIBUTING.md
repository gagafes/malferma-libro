# Contributing

Contributions to this project are licensed under GPL-3.0-or-later. Third-party
files must retain their own licenses and attribution. Do not add books,
voice models, personal settings, or access tokens to the repository.

Use Debian 13 and the system `/usr/bin/python3`. Runtime and build dependencies
are listed in [README.md](README.md).

1. Keep each change small and focused on one clear goal. Prefer ordinary
   functions and existing components over new layers of abstraction.
2. When changing behavior, add a check that can catch a real regression.
   Avoid tests that merely enforce incidental implementation details.
3. Run `make test` and `make translations`. For GTK changes, also test the
   window in a live graphical session: a narrow window, 200% scaling,
   light and dark themes, RTL layout, keyboard navigation, and the
   accessibility menu.
4. Keep the RU/EN/DE/UK manuals consistent with the application's behavior.
   Bundled documentation must match the root-level files before a release.
5. Describe the problem, the resulting behavior, and the checks you ran.
   State separately which checks you could not run.

Edit translations in `po/*.po`; MO files are compiled output.
Check the catalogs with `/usr/bin/python3 packaging/translations.py --check`.
Do not automatically bump the version for every change. The current release
line is 0.1.0; version 1.0 is reserved for a production-ready release.

Build archives, caches, virtual environments, and personal book libraries are
excluded from Git. Before committing, check `git status` and review the staged
files. Do not add a nonexistent GitHub URL or repository owner to the metadata.

## Working with GitHub

The project is hosted at
[gagafes/malferma-libro](https://github.com/gagafes/malferma-libro) on the `main`
branch. Get the source with **Code → Download ZIP**, or clone it:

```sh
git clone https://github.com/gagafes/malferma-libro.git
cd malferma-libro
```

For an existing working tree, check `git remote -v`. Do not add or overwrite
an `origin` that is already configured. If you do not have write access to the
main repository, fork it to your account, clone your fork, and submit your
change through a pull request.

Before your first commit, check your author name and email address with
`git config user.name` and `git config user.email`. If they are not set,
configure your own values locally for this repository. GitHub lets you use
your `noreply` address if you prefer to keep your personal email private.

From the project directory, run:

```sh
git switch -c short-description
make check
make release
git status --short
git add .
git diff --cached --stat
git diff --cached --check
```

Review the staged changes with `git diff --cached`. Include code, resources,
translations, tests, licenses, documentation, and build scripts in the commit.
Keep `dist/`, personal books, voice models, and secrets out of the commit.
Then create a commit with a clear description and push the branch to your
repository:

```sh
git commit -m "Describe the change"
git push -u origin short-description
```

Open a pull request against `main` in the main project. Authenticate to GitHub
using a supported credential manager, SSH, or a token. Do not put a token in
a URL, source file, or project instructions.

GitHub Actions checks the source tree and builds the release files. Pushing
alone does not publish a GitHub Release. After a successful **Check and build**
run in [Actions](https://github.com/gagafes/malferma-libro/actions), download
the `malferma-libro-current` artifact containing the DEB package, source
archives, and `SHA256SUMS`. You must be signed in to GitHub to download it.
The [0.1.0 development prerelease](https://github.com/gagafes/malferma-libro/releases/tag/v0.1.0)
provides a direct DEB download, matching source archives, and checksums.
When publishing a release, use the files from one current build in `dist/`,
keeping older builds outside the current source tree.
