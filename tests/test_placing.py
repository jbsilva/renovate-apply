"""Placing a bare version: which copy in the file belongs to which dependency."""

from dataclasses import replace

import pytest

from renovate_apply.errors import ReplaceError
from renovate_apply.models import Update
from renovate_apply.replace import apply_all, apply_to_text


def _update(  # noqa: PLR0913 - each argument is one field the tests vary
    name: str,
    versions: tuple[str, str],
    neighbors: tuple[str, ...],
    *,
    manager: str = "pep621",
    package_file: str = "pyproject.toml",
    package_name: str | None = None,
) -> Update:
    """Return an update with no replaceString, the way npm, pep621 or helm report one."""
    return Update(
        manager=manager,
        package_file=package_file,
        dep_name=name,
        update_type="patch",
        branch_name="renovate/patch",
        current_value=versions[0],
        new_value=versions[1],
        neighbors=neighbors,
        package_name=package_name,
    )


def test_a_version_is_not_the_start_of_a_longer_one() -> None:
    """==4.2 inside ==4.2.11 is another version, and writing there corrupts it."""
    text = 'a = ["Django==4.2.11"]\nb = ["django==4.2"]\n'
    update = _update("django", ("==4.2", "==4.2.16"), ("Django",))
    assert apply_to_text(text, update) == 'a = ["Django==4.2.11"]\nb = ["django==4.2.16"]\n'


def test_an_extra_named_like_another_dependency_is_part_of_this_one() -> None:
    """In celery[redis], redis is an extra of celery, not the redis dependency."""
    text = 'd = ["celery[redis]>=5.3", "redis>=5.0"]\n'
    update = _update("celery", (">=5.3", ">=5.4"), ("redis",))
    assert apply_to_text(text, update) == 'd = ["celery[redis]>=5.4", "redis>=5.0"]\n'


def test_a_name_in_a_url_does_not_claim_a_version_after_a_plain_name() -> None:
    """A chart repository URL that holds another chart's name is not that chart."""
    text = (
        "- name: grafana\n  repository: https://grafana.github.io/charts\n  version: 7.0.11\n"
        "- name: loki\n  repository: https://grafana.github.io/charts\n  version: 5.41.4\n"
    )
    update = _update(
        "loki", ("5.41.4", "5.42.0"), ("grafana",), manager="helmv3", package_file="Chart.yaml"
    )
    assert apply_to_text(text, update).endswith("version: 5.42.0\n")


def test_a_name_in_a_url_still_counts_when_the_dependency_is_named_by_one() -> None:
    """A pre-commit hook is named by its URL, so the next hook's URL ends its claim."""
    text = (
        "- repo: https://github.com/crate-ci/typos\n  rev: v1.0\n"
        "- repo: https://github.com/astral-sh/ruff-pre-commit\n  rev: v1.0\n"
    )
    update = _update(
        "astral-sh/ruff-pre-commit",
        ("v1.0", "v1.1"),
        ("crate-ci/typos",),
        manager="pre-commit",
        package_file=".pre-commit-config.yaml",
    )
    assert apply_to_text(text, update).endswith("ruff-pre-commit\n  rev: v1.1\n")


@pytest.mark.parametrize(
    "text",
    [
        '"lodash": "npm:lodash-es@^4.17.21",\n"lodash-es": "^4.17.21"\n',
        '"lodash-es": "^4.17.20",\n"lodash": "npm:lodash-es@^4.17.21"\n',
    ],
)
def test_an_alias_whose_name_is_inside_its_package_keeps_its_own_version(text: str) -> None:
    """The lodash key of "npm:lodash-es@..." is the alias, wherever lodash-es is listed."""
    update = _update(
        "lodash",
        ("^4.17.21", "^4.17.22"),
        ("lodash-es",),
        manager="npm",
        package_file="package.json",
        package_name="lodash-es",
    )
    assert '"lodash": "npm:lodash-es@^4.17.22"' in apply_to_text(text, update)


def test_a_version_is_not_the_end_of_a_longer_one() -> None:
    """A crate named serde-demo at 0.1.0 is not serde at 1.0."""
    # cspell:ignore nserde
    text = '[package]\nname = "serde-demo"\nversion = "0.1.0"\n[dependencies]\nserde = "1.0"\n'
    update = _update("serde", ("1.0", "1.1"), (), manager="cargo", package_file="Cargo.toml")
    assert apply_to_text(text, update).endswith('serde = "1.1"\n')


def test_more_copies_than_the_report_lists_stops_the_edit() -> None:
    """A wrapper chart named and versioned like its dependency has two copies and one dependency."""
    text = "name: redis\nversion: 19.0.1\ndependencies:\n  - name: redis\n    version: 19.0.1\n"
    update = _update("redis", ("19.0.1", "19.6.4"), (), manager="helmv3", package_file="Chart.yaml")
    with pytest.raises(ReplaceError, match="not clear which one"):
        apply_to_text(text, update)


@pytest.mark.parametrize(
    "line",
    [
        'tomli = { python = "<3.11", version = "^2.0" }',
        'tomli = { markers = "python_version < \'3.11\'", version = "^2.0" }',
    ],
)
def test_a_key_of_the_dependency_own_table_is_not_another_dependency(line: str) -> None:
    """In poetry, python and markers inside tomli's table are tomli's settings."""
    text = f'python = "^3.10"\n{line}\n'
    update = _update("tomli", ("^2.0", "^2.1"), ("python",), manager="poetry")
    assert '"^2.1"' in apply_to_text(text, update)


@pytest.mark.parametrize(
    "line",
    [
        "git+https://github.com/acme/toolkit@v1.4.0#egg=toolkit",
        "-e git+https://github.com/acme/toolkit.git@v1.4.0",
    ],
)
def test_a_git_requirement_is_named_by_its_url(line: str) -> None:
    """Pip reports the URL as the package name and its last segment as the name, not an alias."""
    update = _update(
        "toolkit",
        ("v1.4.0", "v1.5.0"),
        (),
        manager="pip_requirements",
        package_file="requirements.txt",
        package_name=line.split("@", maxsplit=1)[0].removeprefix("-e ").removeprefix("git+"),
    )
    assert "@v1.5.0" in apply_to_text(f"{line}\n", update)


def test_an_npm_dependency_is_found_under_its_own_dep_type() -> None:
    """Renovate lists devDependencies before peerDependencies, whatever the file's order."""
    text = '{"peerDependencies": {"react": "^18.2.0"}, "devDependencies": {"react": "^18.2.0"}}\n'
    update = replace(
        _update("react", ("^18.2.0", "^19.0.0"), (), manager="npm", package_file="package.json"),
        dep_type="devDependencies",
    )
    assert apply_to_text(text, update) == text.replace(
        '{"react": "^18.2.0"}}', '{"react": "^19.0.0"}}'
    )


def test_a_brace_inside_a_string_does_not_end_the_dep_type_object() -> None:
    """A script value with a brace or an escaped quote is still inside its own object."""
    text = '{"devDependencies": {"a": "x \\" }", "react": "^18.2.0"}, "react": "^18.2.0"}\n'
    update = replace(
        _update(
            "react", ("^18.2.0", "^19.0.0"), ("a",), manager="npm", package_file="package.json"
        ),
        dep_type="devDependencies",
    )
    assert apply_to_text(text, update).endswith('"react": "^19.0.0"}, "react": "^18.2.0"}\n')


def test_two_copies_and_one_edit_stop_where_the_file_has_no_sections() -> None:
    """Go and toolchain at one version are two copies, and only one of them is being moved."""
    text = "go 1.21.0\n\ntoolchain go1.21.0\n\nrequire example.com/go 1.21.0\n"
    update = _update("go", ("1.21.0", "1.23.4"), (), manager="gomod", package_file="go.mod")
    with pytest.raises(ReplaceError, match="not clear which one"):
        apply_to_text(text, update)


def test_a_version_after_a_name_ending_in_a_digit_is_whole() -> None:
    """boto3==1.34.84 is boto3's version; only a bare number checks the character before it."""
    text = "boto3==1.34.84\n"
    update = _update(
        "boto3", ("==1.34.84", "==1.35.0"), (), manager="pip_requirements", package_file="r.txt"
    )
    assert apply_to_text(text, update) == "boto3==1.35.0\n"


def test_a_python_name_spelled_apart_from_its_package_name_is_no_alias() -> None:
    """Renovate gives PyYAML the package name pyyaml, its normal form, not another package."""
    update = _update("PyYAML", ("==6.0.1", "==6.0.2"), (), package_name="pyyaml")
    assert apply_to_text('d = ["PyYAML==6.0.1"]\n', update) == 'd = ["PyYAML==6.0.2"]\n'


def test_a_bare_version_inside_a_range_is_not_a_copy() -> None:
    """PackageManager pnpm@9.1.0 is the copy; engines >=9.1.0 is a range of another entry."""
    text = '{"packageManager": "pnpm@9.1.0", "engines": {"pnpm": ">=9.1.0"}}\n'
    update = replace(
        _update("pnpm", ("9.1.0", "9.2.0"), (), manager="npm", package_file="package.json"),
        dep_type="packageManager",
    )
    assert '"pnpm@9.2.0"' in apply_to_text(text, update)


def test_a_version_listed_before_its_name_belongs_to_its_own_entry() -> None:
    """In "- version: 18.1.0" under redis's entry, the version is postgresql's, not redis's."""
    text = (
        "dependencies:\n"
        "  - name: redis\n    repository: https://charts.example\n"
        "  - version: 18.1.0\n    name: postgresql\n"
    )
    update = _update(
        "redis", ("18.1.0", "18.2.0"), ("postgresql",), manager="helmv3", package_file="Chart.yaml"
    )
    with pytest.raises(ReplaceError, match="is not in"):
        apply_to_text(text, update)


def test_a_deeper_list_item_stays_in_the_name_entry() -> None:
    """A pre-commit rev written after its hooks list is still the repo's rev."""
    text = "repos:\n  - repo: https://github.com/a/b\n    hooks:\n      - id: x\n    rev: v1.0\n"
    update = _update(
        "a/b", ("v1.0", "v1.1"), (), manager="pre-commit", package_file=".pre-commit-config.yaml"
    )
    assert apply_to_text(text, update).endswith("rev: v1.1\n")


def _npm(name: str, dep_type: str, new: str = "^19.0.0") -> Update:
    """Return an npm range update under *dep_type*, as Renovate reports a package.json entry."""
    return replace(
        _update(name, ("^18.2.0", new), (), manager="npm", package_file="package.json"),
        dep_type=dep_type,
    )


def test_each_npm_section_is_searched_on_its_own() -> None:
    """A pnpm override never resumes from the devDependencies edit into peerDependencies."""
    text = (
        '{"devDependencies": {"react": "^18.2.0"}, "peerDependencies": {"react": "^18.2.0"}, '
        '"pnpm": {"overrides": {"react": "^18.2.0"}}}\n'
    )
    updates = [_npm("react", "devDependencies"), _npm("react", "pnpm.overrides")]
    assert apply_all(text, updates) == (
        '{"devDependencies": {"react": "^19.0.0"}, "peerDependencies": {"react": "^18.2.0"}, '
        '"pnpm": {"overrides": {"react": "^19.0.0"}}}\n'
    )


def test_an_npm_section_earlier_in_the_file_is_still_edited() -> None:
    """Renovate reports dependencies before overrides, whatever the file's order."""
    text = '{"overrides": {"lodash": "^18.2.0"}, "dependencies": {"lodash": "^18.2.0"}}\n'
    updates = [_npm("lodash", "dependencies"), _npm("lodash", "overrides")]
    assert apply_all(text, updates) == text.replace("^18.2.0", "^19.0.0")


def _crate(name: str, versions: tuple[str, str], neighbors: tuple[str, ...], table: str) -> Update:
    """Return a Cargo update under *table*, as Renovate reports a Cargo.toml entry."""
    update = _update(name, versions, neighbors, manager="cargo", package_file="Cargo.toml")
    return replace(update, dep_type=table)


def test_a_cargo_table_body_belongs_to_its_own_crate() -> None:
    """In [dependencies.uuid], the serde feature is uuid's; with-uuid in sea-orm is not uuid."""
    text = (
        '[dependencies.uuid]\nfeatures = ["serde", "v4"]\nversion = "1.0"\n\n'
        '[dependencies.serde]\nversion = "1.0"\n\n'
        '[dependencies.sea-orm]\nfeatures = ["sqlx-postgres", "with-uuid"]\nversion = "1.0"\n'
    )
    update = _crate("uuid", ("1.0", "1.10"), ("serde", "sea-orm"), "dependencies")
    assert apply_to_text(text, update) == text.replace(
        'v4"]\nversion = "1.0"', 'v4"]\nversion = "1.10"'
    )


def test_a_crate_in_two_cargo_tables_is_found_in_its_own() -> None:
    """[dependencies] and [dev-dependencies] can pin one crate at one version on two branches."""
    text = '[dependencies.tokio]\nversion = "1.38"\n\n[dev-dependencies.tokio]\nversion = "1.38"\n'
    update = _crate("tokio", ("1.38", "1.39"), (), "dev-dependencies")
    assert apply_to_text(text, update).endswith('[dev-dependencies.tokio]\nversion = "1.39"\n')


def test_a_cargo_target_table_has_the_dep_type_of_its_kind() -> None:
    """[target.'cfg(unix)'.dependencies] holds dependencies too, and both copies are edited."""
    text = (
        '[dependencies]\ntokio = { version = "1.35.0", features = ["rt"] }\n\n'
        "[target.'cfg(unix)'.dependencies]\n"
        'tokio = { version = "1.35.0", features = ["full"] }\nnix = "0.27.1"\n'
    )
    tokio = _crate("tokio", ("1.35.0", "1.36.0"), ("nix",), "dependencies")
    nix = _crate("nix", ("0.27.1", "0.28.0"), ("tokio",), "dependencies")
    assert apply_all(text, [tokio, tokio, nix]) == (
        text.replace("1.35.0", "1.36.0").replace("0.27.1", "0.28.0")
    )


def test_a_python_dependency_in_two_groups_is_one_edit_per_line() -> None:
    """Pep621 has no sections here, so two depTypes at one version are two copies of one key."""
    text = 'dependencies = ["httpx==0.27.0"]\n[dependency-groups]\ndev = ["httpx==0.27.0"]\n'
    first = replace(_update("httpx", ("==0.27.0", "==0.28.0"), ()), dep_type="project.dependencies")
    second = replace(first, dep_type="dependency-groups")
    assert apply_all(text, [first, second]) == text.replace("0.27.0", "0.28.0")


def test_an_npm_key_is_a_direct_member_not_a_nested_one() -> None:
    """devEngines.packageManager is not packageManager, even when it comes first."""
    text = (
        '{"devEngines": {"packageManager": {"name": "pnpm", "version": "9.1.0"}},\n'
        ' "packageManager": "pnpm@9.1.0"}\n'
    )
    update = replace(
        _update("pnpm", ("9.1.0", "9.12.0"), (), manager="npm", package_file="package.json"),
        dep_type="packageManager",
    )
    assert apply_to_text(text, update).endswith('"packageManager": "pnpm@9.12.0"}\n')


@pytest.mark.parametrize(
    "header",
    [
        "[target.'cfg(unix)'.dependencies] # unix only",
        '[target."cfg(target_os = \\"linux\\")".dependencies]',
    ],
)
def test_a_cargo_header_with_a_comment_or_escaped_quotes_is_a_section(header: str) -> None:
    """Both copies move, because the target table is searched as a dependencies table."""
    # cspell:ignore nlibc
    text = (
        '[dependencies]\nlibc = "0.2.150"\n\n[dev-dependencies]\ntempfile = "3"\n\n'
        f'{header}\nlibc = "0.2.150"\n'
    )
    libc = _crate("libc", ("0.2.150", "0.2.151"), ("tempfile",), "dependencies")
    assert apply_all(text, [libc, libc]) == text.replace("0.2.150", "0.2.151")


def test_fewer_copies_than_the_group_edits_stops_the_edit() -> None:
    """A copy the search cannot see is not left behind under a commit that names it."""
    text = 'dependencies = ["httpx==0.27.0"]\n'
    update = _update("httpx", ("==0.27.0", "==0.28.0"), ())
    with pytest.raises(ReplaceError, match="edits 2 of them"):
        apply_all(text, [update, update])
