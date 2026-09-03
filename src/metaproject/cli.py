"""Main Typer CLI application, command router, and formatting for MetaProject."""

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from metaproject.config import (
    Config,
    detect_git_user_name,
    get_config_dir,
    get_config_file_path,
    load_config,
    save_config,
)
from metaproject.db import get_db, get_universe_summary, query_projects
from metaproject.exceptions import CollisionError, MetaProjectError
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
            "version": "0.5.0",
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


@app.command(name="learn")
def learn_cmd(
    project_dir: Optional[Path] = typer.Argument(
        None,
        help="Project directory to learn from (default: current directory).",
    ),
    all_projects: bool = typer.Option(
        False,
        "--all",
        help="Review all projects found in subdirectories.",
    ),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Central template directory to update (default: ~/.metaproject/templates).",
    ),
    depth: int = typer.Option(
        4,
        "--depth",
        help="Maximum directory traversal depth (default: 4).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Automatically apply improvements without interactive prompts.",
    ),
) -> None:
    """Scan existing projects to harvest customizations and update central templates."""
    from metaproject.learn import (
        apply_learned_enhancement,
        learn_from_project,
        learn_workspace,
    )

    target = (project_dir or Path.cwd()).resolve()

    if all_projects:
        results = learn_workspace(target, templates_path, max_depth=depth)
    else:
        results = [learn_from_project(target, templates_path)]

    total_found = sum(res["total_additions"] for res in results)
    if total_found == 0:
        console.print(f"[green]No new template additions or rules found in {target}.[/green]")
        return

    console.print(
        f"[bold cyan]Discovered {total_found} candidate additions "
        f"across {len(results)} projects:[/bold cyan]\n"
    )

    for res in results:
        if res["total_additions"] == 0:
            continue

        console.print(f"[bold]{res['project_name']}:[/bold]")
        for candidate in res["candidates"]:
            target_file = candidate["target_file"]
            additions = candidate["additions"]
            tmpl_path = Path(candidate["template_path"])

            console.print(f"  • [cyan]{target_file}[/cyan] (+{len(additions)} lines):")
            for line in additions[:5]:
                console.print(f"    [dim]+ {line}[/dim]")
            if len(additions) > 5:
                console.print(f"    [dim]... and {len(additions) - 5} more lines[/dim]")

            should_apply = yes
            if not yes:
                prompt_text = (
                    f"Export these additions from {res['project_name']} into {tmpl_path.name}?"
                )
                should_apply = questionary.confirm(prompt_text, default=True).ask()

            if should_apply:
                applied = apply_learned_enhancement(tmpl_path, additions)
                console.print(
                    f"    [bold green]✓ Appended {applied} new lines to "
                    f"{tmpl_path.name}[/bold green]"
                )
