"""Main Typer CLI application, command router, and formatting for MetaProject."""

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from typer.core import TyperGroup

from metaproject.config import (
    Config,
    detect_git_user_name,
    get_config_dir,
    get_config_file_path,
    load_config,
    save_config,
)
from metaproject.db import get_db, get_universe_summary, query_projects
from metaproject.exceptions import CollisionError, GitError, MetaProjectError
from metaproject.git import ensure_template_repository
from metaproject.scaffold import scaffold_project
from metaproject.templates import seed_templates

console = Console()


def render_config_table(cfg: Config, config_file: Path) -> Table:
    """Render configuration attributes as a Rich Table."""
    table = Table(
        title=f"Configuration Settings ({config_file})",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Setting", style="bold cyan")
    table.add_column("Value", style="green")
    table.add_row("Version", str(cfg.version))
    table.add_row("Author", cfg.author)
    table.add_row("Default Git Branch", cfg.default_branch)
    table.add_row("Projects Home", cfg.project_home)
    table.add_row("Templates Store", cfg.templates_dir)
    table.add_row("Universe Database", cfg.universe_db)
    table.add_row("Auto Git Init", str(cfg.auto_git_init))
    table.add_row("Default License", cfg.default_license)
    return table


def render_universe_summary_table(summary: Dict[str, Any], db_path: Path | str) -> Table:
    """Render universe.db summary statistics as a Rich Table."""
    table = Table(
        title="Project Universe Database Status",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="green")
    table.add_row("Database File", str(db_path))
    table.add_row("Total Projects", str(summary["total_projects"]))
    table.add_row("Active Now", f"[bold green]{summary['active_now']}[/bold green]")
    table.add_row("Last Scanned", str(summary["last_run"]))
    if summary.get("missing_projects", 0) > 0:
        table.add_row("Missing / Deleted", f"[yellow]{summary['missing_projects']}[/yellow]")
    return table


def get_manifest_info() -> Dict[str, Any]:
    """Retrieve package manifest metadata, falling back to static defaults if not installed."""
    try:
        import importlib.metadata

        meta = importlib.metadata.metadata("metaproject")
        deps = [d for d in (meta.get_all("Requires-Dist") or []) if "extra ==" not in d]
        return {
            "name": meta.get("Name", "metaproject"),
            "version": meta.get("Version", "0.1.2"),
            "summary": meta.get(
                "Summary",
                "A CLI tool for scaffolding and managing agentic projects and templates",
            ),
            "author": meta.get("Author", "John Fricker"),
            "license": meta.get("License-Expression") or meta.get("License") or "MIT",
            "requires_python": meta.get("Requires-Python", ">=3.11"),
            "dependencies": deps,
            "entrypoint": "metaproject = metaproject.cli:app",
        }
    except Exception:
        return {
            "name": "metaproject",
            "version": "0.6.0",
            "summary": "A CLI tool for scaffolding and managing agentic projects and templates",
            "author": "John Fricker",
            "license": "MIT",
            "requires_python": ">=3.11",
            "dependencies": [
                "typer>=0.12.0",
                "rich>=13.7.0",
                "sqlite-utils>=3.36",
                "questionary>=2.0.0",
                "jinja2>=3.1.0",
            ],
            "entrypoint": "metaproject = metaproject.cli:app",
        }


def print_manifest_info() -> None:
    """Print package manifest and metadata information."""
    manifest = get_manifest_info()

    table = Table(
        title=f"Package Manifest — {manifest['name']} v{manifest['version']}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="green")
    table.add_row("Name", manifest["name"])
    table.add_row("Version", f"[bold green]{manifest['version']}[/bold green]")
    table.add_row("Summary", manifest["summary"])
    table.add_row("Author", manifest["author"])
    table.add_row("License", manifest["license"])
    table.add_row("Requires Python", manifest["requires_python"])
    if manifest["dependencies"]:
        table.add_row("Dependencies", ", ".join(manifest["dependencies"]))
    table.add_row("CLI Entrypoint", manifest["entrypoint"])

    console.print(table)


def version_callback(value: bool) -> None:
    """Callback for -v / --version option."""
    if value:
        print_manifest_info()
        raise typer.Exit()


app = typer.Typer(
    name="metaproject",
    help="A CLI tool for scaffolding and managing agentic projects and templates.",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "-v",
        "--version",
        help="Print package manifest and version information and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """A CLI tool for scaffolding and managing agentic projects and templates."""
    pass


@app.command(name="init")
def init_cmd(
    source_templates: Optional[Path] = typer.Argument(
        None,
        help="Optional path to source templates to copy into ~/.metaproject/templates.",
    ),
    project_home: Optional[Path] = typer.Argument(
        None,
        help="Optional root directory containing workspaces/projects (default: ~/Projects).",
    ),
    project_home_opt: Optional[Path] = typer.Option(
        None,
        "--project-home",
        help="Override root workspace directory.",
    ),
    config_dir: Optional[Path] = typer.Option(
        None,
        "--config-dir",
        help="Override configuration directory (default: ~/.metaproject).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration and templates.",
    ),
) -> None:
    """Initialize or repair the user environment for metaproject."""
    target_config_dir = get_config_dir(config_dir)
    config_file = get_config_file_path(target_config_dir)

    # If configuration already exists and not forced, display contents and status summary
    if config_file.exists() and not force:
        console.print(f"[bold yellow]Found existing configuration at:[/] {config_file}\n")
        existing_cfg = load_config(config_file)
        console.print(render_config_table(existing_cfg, config_file))

        db_path = Path(existing_cfg.universe_db)
        if db_path.exists():
            db = get_db(db_path)
            summary = get_universe_summary(db)
        else:
            summary = {
                "total_projects": 0,
                "active_now": 0,
                "last_run": "Never",
                "missing_projects": 0,
            }
        console.print()
        console.print(render_universe_summary_table(summary, db_path))

        console.print(
            "\n[dim]Metaproject is already initialized. To re-initialize and overwrite, use:[/dim] "
            "[bold cyan]metaproject init --force[/bold cyan]"
        )
        return

    target_config_dir.mkdir(parents=True, exist_ok=True)
    templates_dest = target_config_dir / "templates"

    effective_home = project_home_opt or project_home

    console.print(f"[bold green]Initializing metaproject in {target_config_dir}...[/bold green]")

    # 1. Seed or copy templates
    if source_templates:
        src_path = source_templates.expanduser().resolve()
        if not src_path.exists() or not src_path.is_dir():
            console.print(
                "[bold red]Error:[/bold red] "
                f"Specified template directory does not exist: {src_path}"
            )
            raise typer.Exit(code=1)
        templates_dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_path, templates_dest, dirs_exist_ok=True)
        console.print(f"[cyan]✓ Copied templates from {src_path} to {templates_dest}[/cyan]")
    else:
        copied = seed_templates(templates_dest, force=force)
        console.print(f"[cyan]✓ Seeded {len(copied)} default templates in {templates_dest}[/cyan]")

    # 1b. Git-back the template store so `learn apply` has provenance (spec.md §4.1)
    try:
        initialized = ensure_template_repository(templates_dest, branch="main")
        if initialized:
            console.print(
                f"[cyan]✓ Initialized template store git repository at {templates_dest}[/cyan]"
            )
    except GitError as git_err:
        console.print(f"[yellow]Notice:[/] Template store git init skipped ({git_err})")

    # 2. Configure defaults
    existing_cfg = load_config(config_file) if config_file.exists() and not force else Config()

    default_author = existing_cfg.author or detect_git_user_name()
    default_home = (
        str(effective_home.expanduser().resolve()) if effective_home else existing_cfg.project_home
    )

    author = default_author
    resolved_home = default_home
    branch = existing_cfg.default_branch

    # If running interactively, prompt for confirmation
    if not force:
        prompt_author = questionary.text("Default Author Name:", default=default_author).ask()
        if prompt_author:
            author = prompt_author.strip()

        prompt_branch = questionary.text("Default Git Branch:", default=branch).ask()
        if prompt_branch:
            branch = prompt_branch.strip()

        prompt_home = questionary.text("Projects Root Directory:", default=resolved_home).ask()
        if prompt_home:
            resolved_home = str(Path(prompt_home).expanduser().resolve())

    universe_db_path = str(target_config_dir / "universe.db")

    new_cfg = Config(
        author=author,
        default_branch=branch,
        project_home=resolved_home,
        templates_dir=str(templates_dest),
        universe_db=universe_db_path,
        auto_git_init=True,
    )

    save_config(new_cfg, config_file)
    console.print(f"[cyan]✓ Saved configuration to {config_file}[/cyan]")

    # Run initial universe scan on project_home if accessible
    home_path = Path(resolved_home)
    if home_path.exists():
        try:
            from metaproject.universe import scan_universe

            db_inst = get_db(universe_db_path)
            console.print(f"[cyan]Indexing workspaces in {home_path}...[/cyan]")
            initial_projects = scan_universe(home_path, max_depth=3, interactive=False, db=db_inst)
            console.print(
                f"[cyan]✓ Cataloged {len(initial_projects)} projects into {universe_db_path}[/cyan]"
            )
        except Exception as scan_err:
            console.print(f"[yellow]Notice:[/] Workspace index deferred ({scan_err})")

    console.print(
        Panel.fit(
            f"[bold green]Metaproject Initialized Successfully![/bold green]\n\n"
            f"[bold]Author:[/bold] {new_cfg.author}\n"
            f"[bold]Projects Home:[/bold] {new_cfg.project_home}\n"
            f"[bold]Templates Store:[/bold] {new_cfg.templates_dir}\n"
            f"[bold]Universe Catalog:[/bold] {new_cfg.universe_db}\n\n"
            f"Run [cyan]metaproject new <name>[/cyan] to scaffold a project.\n"
            f"Run [cyan]metaproject universe[/cyan] to inspect cataloged projects.",
            title="Environment Ready",
        )
    )


# Alias: metaproject install -> metaproject init
@app.command(name="install", hidden=False)
def install_cmd(
    source_templates: Optional[Path] = typer.Argument(
        None,
        help="Optional path to source templates to copy into ~/.metaproject/templates.",
    ),
    project_home: Optional[Path] = typer.Argument(
        None,
        help="Optional root directory containing workspaces/projects (default: ~/Projects).",
    ),
    config_dir: Optional[Path] = typer.Option(
        None,
        "--config-dir",
        help="Override configuration directory (default: ~/.metaproject).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration and templates.",
    ),
) -> None:
    """Alias for 'metaproject init'."""
    init_cmd(
        source_templates=source_templates,
        project_home=project_home,
        config_dir=config_dir,
        force=force,
    )


@app.command(name="new")
def new_cmd(
    project_name: str = typer.Argument(
        ...,
        help="Name of the project to create (used for folder name and default title).",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Destination directory or exact path (default: ./<project-name>).",
    ),
    templates: Optional[Path] = typer.Option(
        None,
        "--templates",
        "-t",
        help="Custom templates directory to render from.",
    ),
    title: Optional[str] = typer.Option(
        None,
        "--title",
        help="Human-readable project title (default: title-cased project name).",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="One-line project summary.",
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help="Author name (default: from config or git identity).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Accept defaults without interactive prompts.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Scaffold into an existing non-empty directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview actions and file paths without writing to disk.",
    ),
    no_git: bool = typer.Option(
        False,
        "--no-git",
        help="Skip git initialization and initial commit.",
    ),
) -> None:
    """Scaffold a new project directory and generate standard SDLC boilerplate."""
    interactive = not yes

    try:
        result = scaffold_project(
            project_name=project_name,
            output=output,
            templates_dir=templates,
            title=title,
            description=description,
            author=author,
            interactive=interactive,
            force=force,
            dry_run=dry_run,
            no_git=no_git,
        )
    except CollisionError as exc:
        console.print(f"[bold red]Collision Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except MetaProjectError as exc:
        console.print(f"[bold red]Scaffolding Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    target_dir = result["target_dir"]
    variables = result["variables"]
    rendered = result["rendered_files"]
    git_init = result["git_initialized"]

    if dry_run:
        console.print(f"[bold yellow]DRY RUN:[/] Would create project at [bold]{target_dir}[/]")
    else:
        console.print(f"[bold green]Successfully scaffolded project at:[/] [bold]{target_dir}[/]")

    table = Table(title="Generated Project Files", show_header=True, header_style="bold magenta")
    table.add_column("Relative Path", style="cyan")
    table.add_column("Type", style="green")

    for item in sorted(rendered):
        rel = item.relative_to(target_dir)
        kind = "Directory" if item.is_dir() else "File"
        table.add_row(str(rel), kind)

    console.print(table)

    summary = (
        f"[bold]Project Title:[/bold] {variables['ProjectTitle']}\n"
        f"[bold]Author:[/bold] {variables['Author']}\n"
        f"[bold]Date:[/bold] {variables['Date']}\n"
        f"[bold]Git Initialized:[/bold] {'Yes (branch main)' if git_init else 'Skipped'}"
    )
    console.print(Panel.fit(summary, title="Project Details"))


CLASSIFICATION_COLORS = {
    "Active Now": "[bold green]Active Now[/bold green]",
    "Active Near": "[green]Active Near[/green]",
    "Active Far": "[yellow]Active Far[/yellow]",
    "Idle": "[dim yellow]Idle[/dim yellow]",
    "Ancient": "[dim red]Ancient[/dim red]",
    "Archived": "[dim blue]Archived[/dim blue]",
}


@app.command(name="universe")
def universe_cmd(
    target_dir: Optional[str] = typer.Argument(
        None,
        help="Starting scan directory or 'summary' (default: cwd or project_home).",
    ),
    db_path: Optional[Path] = typer.Option(
        None,
        "--db",
        help="Path to SQLite universe database (default: ~/.metaproject/universe.db).",
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        "-s",
        help="Display status summary of universe.db without scanning.",
    ),
    classification_filter: Optional[str] = typer.Option(
        None,
        "--filter",
        help="Filter output by classification (e.g. 'Active Now', 'Archived').",
    ),
    depth: int = typer.Option(
        4,
        "--depth",
        help="Maximum directory traversal depth (default: 4).",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        help="Output format: table, json, or csv.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Run silently and refresh the database without printing.",
    ),
    list_only: bool = typer.Option(
        False,
        "--list",
        "-l",
        help="List cataloged projects from database without scanning disk.",
    ),
    show_missing: bool = typer.Option(
        False,
        "--show-missing",
        help="Include projects previously cataloged that are now missing.",
    ),
    show_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Show all cataloged projects across all workspaces.",
    ),
) -> None:
    """Catalog and classify all projects across subdirectories into a SQLite database."""
    import csv
    import io
    import json

    from metaproject.db import get_db, get_universe_summary
    from metaproject.universe import scan_universe

    cfg = load_config()
    resolved_db_path = db_path or Path(cfg.universe_db)

    # Check if summary mode requested (via 'summary' argument or --summary flag)
    is_summary = summary or (target_dir is not None and target_dir.strip().lower() == "summary")
    if is_summary:
        if resolved_db_path.exists():
            db = get_db(resolved_db_path)
            summary_data = get_universe_summary(db)
        else:
            summary_data = {
                "total_projects": 0,
                "active_now": 0,
                "last_run": "Never",
                "missing_projects": 0,
            }
        if output_format == "json":
            out = {"database": str(resolved_db_path), **summary_data}
            console.print_json(json.dumps(out, indent=2))
            return

        if output_format == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "database",
                    "total_projects",
                    "active_now",
                    "last_run",
                    "missing_projects",
                ],
            )
            writer.writeheader()
            writer.writerow({"database": str(resolved_db_path), **summary_data})
            console.print(output.getvalue().strip())
            return

        console.print(
            f"[bold cyan]Universe DB status:[/] "
            f"[bold]{summary_data['total_projects']}[/] projects "
            f"([bold green]{summary_data['active_now']}[/] active now)",
            soft_wrap=True,
        )
        console.print(
            f"[bold cyan]Last update to the db:[/] {summary_data['last_run']}",
            soft_wrap=True,
        )
        return

    # Determine target directory
    start_path = (Path(target_dir) if target_dir else Path.cwd()).expanduser().resolve()
    db = get_db(resolved_db_path)

    if not list_only:
        if not quiet:
            console.print(
                f"[cyan]Scanning universe from: [bold]{start_path}[/bold] (depth {depth})...[/cyan]"
            )
        scan_universe(start_path, max_depth=depth, interactive=False, db=db)

    # By default, scope output to start_path unless --all is passed
    # (or if --list was called without a specific target_dir)
    scope_path = None if (show_all or (list_only and target_dir is None)) else str(start_path)

    projects = query_projects(
        db,
        path_prefix=scope_path,
        classification=classification_filter,
        include_missing=show_missing,
    )

    if quiet:
        return

    if output_format == "json":
        console.print_json(json.dumps(projects, indent=2))
        return

    if output_format == "csv":
        output = io.StringIO()
        if projects:
            writer = csv.DictWriter(output, fieldnames=list(projects[0].keys()))
            writer.writeheader()
            writer.writerows(projects)
        console.print(output.getvalue())
        return

    # Default: Rich Table
    table = Table(
        title=f"Project Universe Catalog ({len(projects)} projects)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Classification", style="bold")
    table.add_column("Project", style="bold cyan")
    table.add_column("Relative Path", style="dim")
    table.add_column("Last Modified", style="green")
    table.add_column("Git", justify="center")
    table.add_column("SDLC", justify="center")

    for proj in projects:
        c_badge = CLASSIFICATION_COLORS.get(proj["classification"], proj["classification"])
        git_badge = (
            f"[cyan]{proj['git_branch'] or 'git'}[/cyan]" if proj["is_git"] else "[dim]no[/dim]"
        )
        sdlc_badges = []
        if proj["has_agents_md"]:
            sdlc_badges.append("A")
        if proj["has_intent_md"]:
            sdlc_badges.append("I")
        if proj["has_state_md"]:
            sdlc_badges.append("S")
        if proj["has_handoff_md"]:
            sdlc_badges.append("H")
        sdlc_str = "".join(sdlc_badges) if sdlc_badges else "-"

        table.add_row(
            c_badge,
            proj["title"] or proj["name"],
            proj["relative_path"],
            proj["last_modified"][:10],
            git_badge,
            sdlc_str,
        )

    console.print(table)


@app.command(name="review")
def review_cmd(
    project_dir: Optional[Path] = typer.Argument(
        None,
        help="Project directory to review (default: current directory).",
    ),
    all_projects: bool = typer.Option(
        False,
        "--all",
        help="Review all projects found in subdirectories.",
    ),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Template directory to compare against (default: ~/.metaproject/templates).",
    ),
    depth: int = typer.Option(
        4,
        "--depth",
        help="Maximum directory traversal depth (default: 4).",
    ),
) -> None:
    """Analyze projects against central templates to detect missing files and drift."""
    from metaproject.review import review_project, review_workspace

    target = (project_dir or Path.cwd()).resolve()

    if all_projects:
        results = review_workspace(target, templates_path, max_depth=depth)
    else:
        results = [review_project(target, templates_path)]

    if not results:
        console.print(f"[yellow]No projects discovered for review in {target}[/yellow]")
        return

    table = Table(
        title=f"Project Drift & Governance Review ({len(results)} projects)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Project", style="bold cyan")
    table.add_column("Compliance", justify="center")
    table.add_column("Missing Files", style="red")
    table.add_column("Template Drift", style="yellow")

    for res in results:
        compliance = (
            "[bold green]PASS[/bold green]" if res["is_compliant"] else "[bold red]DRIFT[/bold red]"
        )
        missing = ", ".join(res["missing_files"]) if res["missing_files"] else "[dim]None[/dim]"
        drift_files = ", ".join(res["diffs"].keys()) if res["diffs"] else "[dim]None[/dim]"
        table.add_row(res["project_name"], compliance, missing, drift_files)

    console.print(table)

    # Print recommendations if any
    all_recs = []
    for res in results:
        for rec in res["recommendations"]:
            all_recs.append(f"[bold]{res['project_name']}:[/bold] {rec}")

    if all_recs:
        rec_text = "\n".join(f"• {r}" for r in all_recs)
        console.print(Panel(rec_text, title="Actionable Recommendations", border_style="yellow"))


# --------------------------------------------------------------------------- learn
#
# `learn` is a command group whose *default* is the scan-then-review flow (spec.md
# §5.4.4). The subcommands and the acceptance TUI are two interfaces to one queue: both
# call the same `metaproject.learn` public API and both write through to `universe.db`
# immediately, so a review session can be abandoned and finished from the CLI without
# divergence.

LEARN_DEFAULT_COMMAND = "__default__"


class LearnGroup(TyperGroup):
    """A `learn` group whose bare and `learn [root]` forms run the default mode.

    Click resolves the first argument as a subcommand name, so `learn [root]` would
    otherwise be "no such command '<root>'". Rather than hanging an optional positional
    off the group — which would swallow `learn scan` as a path — anything that is not a
    known subcommand is routed to a hidden default command that carries the real
    signature. `--help` still belongs to the group.
    """

    def parse_args(self, ctx, args):
        if not args or (args[0] not in self.commands and args[0] not in ("--help", "-h")):
            args = [LEARN_DEFAULT_COMMAND, *args]
        return super().parse_args(ctx, args)


learn_app = typer.Typer(
    name="learn",
    help=(
        "Harvest recurring project drift into reviewed template proposals.\n\n"
        "Default mode: `metaproject learn [ROOT] [--no-tui]` scans and then reviews the "
        "resulting queue in the acceptance TUI. It also accepts every `learn scan` "
        "option (--all, --depth, --since, --yes, --model, --templates). A scan never "
        "mutates a template; writes happen only on an accept.\n\n"
        "`--templates <path>` is available on every subcommand "
        "(default: ~/.metaproject/templates)."
    ),
    cls=LearnGroup,
    no_args_is_help=False,
)
app.add_typer(learn_app, name="learn")

STATUS_STYLES = {
    "pending": "[yellow]pending[/yellow]",
    "applied": "[green]applied[/green]",
    "rejected": "[dim]rejected[/dim]",
}


def learn_db():
    """Open the proposal ledger the way every `learn` subcommand opens it."""
    from metaproject.db import get_db as _get_db

    return _get_db(load_config().universe_db)


def resolve_templates_dir(templates_path: Optional[Path]) -> Path:
    """The template store a `learn` subcommand operates on (`--templates` wins)."""
    if templates_path:
        return Path(templates_path).expanduser().resolve()
    return Path(load_config().templates_dir).expanduser().resolve()


def open_in_editor(text: str, suffix: str = ".md") -> Optional[str]:
    """Open the proposal body in `$EDITOR`, delegating to the TUI's implementation.

    `learn edit` and the TUI's `e` are the same action reached two ways, so they share
    one implementation rather than two copies that can drift (plan.md §1.3.2). None
    means the edit aborted — no `$EDITOR`, a non-zero exit, or nothing changed — and
    the caller's answer to all three is the same: keep the candidate pending.
    """
    from metaproject.learn.tui import open_in_editor as _open_in_editor

    return _open_in_editor(text, suffix)


def render_proposal_table(rows, verbose: bool = False) -> Table:
    """The `learn list` queue table (spec.md §5.4.4)."""
    table = Table(
        title=f"Learn Proposal Queue ({len(rows)} proposals)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("ID", justify="right", style="bold cyan")
    table.add_column("Target File", style="bold")
    table.add_column("Title")
    table.add_column("Projects", justify="right")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Status", justify="center")
    if verbose:
        table.add_column("Section", style="dim")

    for row in rows:
        cells = [
            str(row["id"]),
            str(row["target_file"]),
            str(row["title"]),
            str(row["evidence_count"]),
            f"{float(row['evidence_score'] or 0.0):.2f}",
            STATUS_STYLES.get(str(row["status"]), str(row["status"])),
        ]
        if verbose:
            cells.append(str(row["target_section"] or "—"))
        table.add_row(*cells)
    return table


def print_plan(plan) -> None:
    """Show the operator exactly what would be written, before anything is."""
    from metaproject.learn.apply import PLACEMENT_APPEND, PLACEMENT_NEW_FILE

    console.print(
        Panel.fit(
            f"[bold]{plan.title}[/bold]\n\n"
            f"[bold]Target:[/bold] {plan.target_file} → {plan.template_file}\n"
            f"[bold]Section:[/bold] {plan.target_section or '—'}\n"
            f"[bold]Projects:[/bold] "
            f"{', '.join(plan.contributing_projects) or '—'}\n\n"
            f"{plan.rationale}",
            title=f"Proposal #{plan.proposal_id}",
        )
    )
    if plan.fallback_reason:
        console.print(f"[bold yellow]Warning:[/bold yellow] {plan.fallback_reason}")
    elif plan.placement == PLACEMENT_NEW_FILE:
        console.print(f"[cyan]This creates a new template file: {plan.template_file}[/cyan]")
    elif plan.placement == PLACEMENT_APPEND:
        console.print("[dim]No target section was proposed; appending at end of file.[/dim]")

    diff = plan.diff()
    if diff:
        console.print(Syntax(diff, "diff", theme="ansi_dark", word_wrap=True))
    else:
        console.print("[dim]The template already carries this content; nothing to write.[/dim]")


def apply_one(db, proposal_id: int, templates_dir: Path, yes: bool, edited_body=None) -> bool:
    """Review one proposal's diff, confirm, write, and commit. True if it was applied."""
    from metaproject.learn.apply import apply_plan, plan_apply

    plan = plan_apply(db, proposal_id, templates_dir=templates_dir, edited_body=edited_body)
    print_plan(plan)

    prompt = f"Apply proposal #{proposal_id} to {plan.template_file.name}?"
    if not yes and not typer.confirm(prompt):
        console.print("[yellow]Skipped. The proposal stays pending.[/yellow]")
        return False

    result = apply_plan(db, plan, templates_dir, edited_body=edited_body)
    if result.changed:
        console.print(
            f"[bold green]Applied proposal #{proposal_id}[/bold green] "
            f"→ {result.plan.template_file} (commit {str(result.commit)[:12]})"
        )
    else:
        console.print(
            f"[cyan]Proposal #{proposal_id} was already satisfied by the template; "
            "marked applied without a commit.[/cyan]"
        )
    return True


def perform_scan(
    root: Optional[Path],
    all_projects: bool,
    depth: int,
    since: Optional[str],
    yes: bool,
    model: Optional[str],
    templates_dir: Path,
):
    """Run stages 1–4 and report them. Shared by `learn scan` and the default mode.

    Both entry points call this rather than each assembling their own pipeline, so the
    default mode cannot quietly scan differently from the subcommand.
    """
    from metaproject.learn import scan

    cfg = load_config()
    target = Path(cfg.project_home) if all_projects else (root or Path.cwd())

    try:
        result = scan(
            target,
            templates_dir=templates_dir,
            db=learn_db(),
            config=cfg,
            depth=depth,
            since=since,
            yes=yes,
            model=model,
        )
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)
    except MetaProjectError as exc:
        console.print(f"[bold red]Learn failed:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if result.aborted:
        console.print("[yellow]Send declined. Nothing was sent to the model.[/yellow]")
        return None

    console.print(
        f"[bold green]Scanned {result.projects_scanned} projects[/bold green] "
        f"({result.files_scanned} files with drift) → {result.created} proposals recorded."
    )
    if result.skipped:
        console.print(
            f"[yellow]Run marked '{result.status}'. Skipped target files: "
            f"{', '.join(result.skipped)}[/yellow]"
        )
    return result


def open_review_queue(
    rows,
    templates_dir: Path,
    no_tui: bool = False,
) -> None:
    """Review the queue in the TUI, or degrade to the `list` table (spec.md §5.4.5).

    An empty queue never opens the reviewer, and the three degradation triggers —
    not a TTY, `--no-tui`, `TERM=dumb` — print the table and exit zero. None of them
    is an error, so scripted and CI use needs no special flag.
    """
    from metaproject.learn import tui

    if not rows:
        console.print("[green]Nothing pending. The templates are current.[/green]")
        return

    if not tui.should_open_tui(rows, no_tui=no_tui):
        console.print(render_proposal_table(rows))
        console.print(
            "[dim]Not a terminal (or --no-tui): showing the queue instead of the "
            "reviewer. Act on it with[/dim] [cyan]metaproject learn apply <id>[/cyan]"
        )
        return

    result = tui.run_review(learn_db(), rows, templates_dir, console=console)
    console.print(
        f"[bold green]{len(result.applied)} applied[/bold green], "
        f"{len(result.rejected)} discarded, {len(result.skipped)} skipped"
        + (f", {len(result.remaining)} left pending" if result.remaining else "")
    )
    for message in result.errors:
        console.print(f"[yellow]{message}[/yellow]")


@learn_app.command(name=LEARN_DEFAULT_COMMAND, hidden=True)
def learn_default_cmd(
    root: Optional[Path] = typer.Argument(
        None,
        help="Workspace root to scan for projects (default: current directory).",
    ),
    all_projects: bool = typer.Option(
        False, "--all", help="Scan the configured projects home instead of the given root."
    ),
    depth: int = typer.Option(4, "--depth", help="Maximum directory traversal depth."),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only scan projects changed since a date (2026-01-01) or within N days.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the egress confirmation for non-interactive use."
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Model passed through to `claude`."),
    no_tui: bool = typer.Option(
        False, "--no-tui", help="Print the queue table instead of opening the reviewer."
    ),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Template store to compare against (default: ~/.metaproject/templates).",
    ),
) -> None:
    """Scan, then review the resulting queue in the acceptance TUI (default mode)."""
    from metaproject.learn import review

    templates_dir = resolve_templates_dir(templates_path)
    result = perform_scan(root, all_projects, depth, since, yes, model, templates_dir)
    if result is None:
        return
    open_review_queue(review(learn_db(), status="pending"), templates_dir, no_tui=no_tui)


@learn_app.command(name="review")
def learn_review_cmd(
    target: Optional[str] = typer.Option(
        None, "--target", help="Only review proposals for this target file."
    ),
    status: str = typer.Option("pending", "--status", help="Which queue to review."),
    min_score: Optional[float] = typer.Option(
        None, "--min-score", help="Only review proposals at or above this evidence score."
    ),
    no_tui: bool = typer.Option(
        False, "--no-tui", help="Print the queue table instead of opening the reviewer."
    ),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Open the acceptance TUI over the existing queue, without scanning."""
    from metaproject.learn import review

    rows = review(
        learn_db(),
        status=None if status in (None, "all") else status,
        target_file=target,
        min_score=min_score,
    )
    open_review_queue(rows, resolve_templates_dir(templates_path), no_tui=no_tui)


@learn_app.command(name="scan")
def learn_scan_cmd(
    root: Optional[Path] = typer.Argument(
        None,
        help="Workspace root to scan for projects (default: current directory).",
    ),
    all_projects: bool = typer.Option(
        False,
        "--all",
        help="Scan the configured projects home instead of the given root.",
    ),
    depth: int = typer.Option(4, "--depth", help="Maximum directory traversal depth."),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only scan projects changed since a date (2026-01-01) or within N days.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the egress confirmation for non-interactive use."
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Model passed through to `claude`."),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Template store to compare against (default: ~/.metaproject/templates).",
    ),
) -> None:
    """Collect drift, synthesize proposals, and record them. Never mutates a template."""
    result = perform_scan(
        root, all_projects, depth, since, yes, model, resolve_templates_dir(templates_path)
    )
    if result is None:
        raise typer.Exit(code=0)
    console.print(
        "[dim]Review them with[/dim] [cyan]metaproject learn review[/cyan] "
        "[dim]or[/dim] [cyan]metaproject learn list[/cyan]"
    )


@learn_app.command(name="list")
def learn_list_cmd(
    status: Optional[str] = typer.Option(
        "pending",
        "--status",
        help="Filter by status: pending, applied, rejected, or 'all'.",
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Include the proposed target section."),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Table of proposals: id, target file, title, evidence count, score."""
    from metaproject.learn import review

    wanted = None if status in (None, "all") else status
    rows = review(learn_db(), status=wanted)
    if not rows:
        console.print("[yellow]No proposals in the queue.[/yellow]")
        return
    console.print(render_proposal_table(rows, verbose=verbose))


@learn_app.command(name="show")
def learn_show_cmd(
    proposal_id: int = typer.Argument(..., help="Proposal id, as shown by `learn list`."),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Full rationale, proposed body, and contributing projects with absolute paths."""
    from metaproject.learn.store import get_evidence, get_proposal

    db = learn_db()
    row = get_proposal(db, proposal_id)
    if row is None:
        console.print(f"[bold red]Error:[/bold red] no proposal with id {proposal_id}")
        raise typer.Exit(code=1)

    body = row["edited_body"] or row["proposed_body"]
    console.print(
        Panel(
            f"[bold]{row['title']}[/bold]\n\n"
            f"[bold]Target:[/bold] {row['target_file']}\n"
            f"[bold]Section:[/bold] {row['target_section'] or '—'}\n"
            f"[bold]Status:[/bold] {row['status']}    "
            f"[bold]Score:[/bold] {float(row['evidence_score'] or 0.0):.2f}    "
            f"[bold]Projects:[/bold] {row['evidence_count']}\n\n"
            f"{row['rationale']}",
            title=f"Proposal #{row['id']}",
        )
    )
    console.print(Syntax(str(body), "markdown", theme="ansi_dark", word_wrap=True))

    evidence = get_evidence(db, proposal_id)
    if evidence:
        # Provenance is printed as lines, not as a table, and with `soft_wrap` on:
        # `show` exists to name *absolute* paths (spec.md §5.4.4), and a table column
        # ellipsizes them at any ordinary terminal width, which turns the one piece of
        # information this view is for into `/private/var/folders/7k/_13bgbq…`.
        console.print("\n[bold magenta]Contributing Projects[/bold magenta]")
        for item in evidence:
            weight = float(item["weight"] or 0.0)
            console.print(
                f"  [green]{weight:>5.2f}[/green]  [cyan]{item['project_path']}[/cyan]",
                soft_wrap=True,
                highlight=False,
            )
            excerpt = str(item["excerpt"] or "").splitlines()
            if excerpt:
                console.print(f"         [dim]{excerpt[0]}[/dim]", soft_wrap=True, highlight=False)


@learn_app.command(name="apply")
def learn_apply_cmd(
    proposal_id: Optional[int] = typer.Argument(None, help="Proposal id to apply."),
    apply_all: bool = typer.Option(False, "--all", help="Apply every pending proposal in turn."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without the diff confirmation."),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Review the diff, write the template, and commit. One commit per accept."""
    from metaproject.learn import review

    if proposal_id is None and not apply_all:
        console.print("[bold red]Error:[/bold red] give a proposal id, or --all.")
        raise typer.Exit(code=1)

    db = learn_db()
    templates_dir = resolve_templates_dir(templates_path)
    ids = (
        [int(row["id"]) for row in review(db, status="pending")]
        if apply_all
        else [int(proposal_id)]
    )
    if not ids:
        console.print("[yellow]No pending proposals to apply.[/yellow]")
        return

    applied = 0
    for pid in ids:
        try:
            if apply_one(db, pid, templates_dir, yes):
                applied += 1
        except MetaProjectError as exc:
            console.print(f"[bold red]Apply failed for #{pid}:[/bold red] {exc}")
            raise typer.Exit(code=1)

    if apply_all:
        console.print(
            f"[bold green]Applied {applied} of {len(ids)} pending proposals.[/bold green]"
        )


@learn_app.command(name="edit")
def learn_edit_cmd(
    proposal_id: int = typer.Argument(..., help="Proposal id to edit before applying."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the edit without confirmation."),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Open the proposed body in $EDITOR; saving applies the edited version."""
    from metaproject.learn.store import get_proposal, set_edited_body

    db = learn_db()
    row = get_proposal(db, proposal_id)
    if row is None:
        console.print(f"[bold red]Error:[/bold red] no proposal with id {proposal_id}")
        raise typer.Exit(code=1)

    original = str(row["edited_body"] or row["proposed_body"] or "")
    edited = open_in_editor(original)
    if edited is None:
        # An aborted edit is a deliberate no-op, not a failure: spec.md §5.4.10 calls
        # for "keep the candidate pending, stay in the TUI", and the subcommand is the
        # same action reached another way (plan.md §1.3.2). It therefore exits zero,
        # as `learn apply` already does when the diff confirmation is declined.
        console.print(
            "[yellow]Edit aborted (no $EDITOR, a non-zero exit, or no change saved). "
            "The proposal stays pending.[/yellow]"
        )
        return

    set_edited_body(db, proposal_id, edited)
    templates_dir = resolve_templates_dir(templates_path)
    try:
        apply_one(db, proposal_id, templates_dir, yes, edited_body=edited)
    except MetaProjectError as exc:
        console.print(f"[bold red]Apply failed:[/bold red] {exc}")
        raise typer.Exit(code=1)


@learn_app.command(name="reject")
def learn_reject_cmd(
    proposal_id: int = typer.Argument(..., help="Proposal id to reject."),
    forget: bool = typer.Option(
        False, "--forget", help="Clear the suppression record entirely instead of suppressing."
    ),
    templates_path: Optional[Path] = typer.Option(
        None, "--templates", help="Template store (default: ~/.metaproject/templates)."
    ),
) -> None:
    """Suppress a proposal by content hash. `--forget` clears the suppression."""
    from metaproject.learn import reject_proposal

    if not reject_proposal(learn_db(), proposal_id, forget=forget):
        console.print(f"[bold red]Error:[/bold red] no proposal with id {proposal_id}")
        raise typer.Exit(code=1)

    if forget:
        console.print(f"[cyan]Forgot proposal #{proposal_id}. A later scan meets it afresh.[/cyan]")
    else:
        console.print(
            f"[cyan]Rejected proposal #{proposal_id}. It resurfaces only on stronger "
            "evidence.[/cyan]"
        )
