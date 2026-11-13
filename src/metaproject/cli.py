"""Main Typer CLI application, command router, and formatting for MetaProject."""

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.console import Console
from rich.markup import escape
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
from metaproject.exceptions import (
    CollisionError,
    GitError,
    MetaProjectError,
    MissingExtraError,
)
from metaproject.extras import INSTALL_HINT, LazyModule, available, require
from metaproject.git import ensure_template_repository, is_git_repository
from metaproject.scaffold import (
    is_directory_empty,
    list_directory_entries,
    resolve_output,
    scaffold_project,
)
from metaproject.session import agent_marker, override_hint, web_profile_reason
from metaproject.skills import CURRENT, INSTALLED, MODIFIED, OUTDATED, UPDATED
from metaproject.templates import seed_templates

console = Console()

# Interactive prompts only; questionary ships in the optional `tui` extra.
questionary = LazyModule("questionary", "Interactive prompts")


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
            "version": "0.9.1",
            "summary": "A CLI tool for scaffolding and managing agentic projects and templates",
            "author": "John Fricker",
            "license": "MIT",
            "requires_python": ">=3.11",
            "dependencies": [
                "typer>=0.12.0",
                "rich>=13.7.0",
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


class MetaprojectGroup(TyperGroup):
    """The root command group: turns a missing optional extra into one clear line.

    `textual`, `questionary` and `sqlite-utils` ship in `metaproject[tui]`. A command
    that reaches for one without it raises `MissingExtraError` (see `extras.require`);
    catching it here, once, means every command (and every `learn` subcommand) reports
    the install command instead of an `ImportError` traceback, and exits 1.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except MissingExtraError as exc:
            console.print(
                f"[bold red]Missing optional dependency:[/bold red] {escape(str(exc))}",
                soft_wrap=True,
            )
            raise typer.Exit(code=1) from exc


app = typer.Typer(
    name="metaproject",
    help="A CLI tool for scaffolding and managing agentic projects and templates.",
    no_args_is_help=True,
    cls=MetaprojectGroup,
)


def web_profile_notice(what: str, output_format: str = "table", instead: str = "") -> bool:
    """Print the one-line web-profile notice for `what`. True when it was printed.

    The caller returns (exit 0) on True: in a Claude Code on the web container there is
    no catalog, no persistent template store and no operator, so these commands have
    nothing to act on. Saying so in one line is the whole answer, not an error.

    A machine-readable `output_format` keeps stdout parseable: the notice goes to
    stderr, and `json` writes an `{"available": false, ...}` envelope to stdout so a
    JSON consumer still receives JSON (`csv` writes nothing to stdout).
    """
    reason = web_profile_reason()
    if reason is None:
        return False
    if output_format in ("json", "csv"):
        Console(stderr=True).print(
            f"[yellow]Notice:[/] {what} is not available in web sessions ({reason}).",
            soft_wrap=True,
        )
        if output_format == "json":
            import json

            envelope = {
                "available": False,
                "profile": "web",
                "reason": reason,
                "notice": f"{what} is not available in web sessions.",
            }
            typer.echo(json.dumps(envelope, indent=2))
        return True
    tail = f"; {instead}" if instead else ""
    console.print(
        f"[yellow]Notice:[/] {what} is not available in web sessions ({reason}){tail}.",
        soft_wrap=True,
    )
    return True


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


def print_skills_report(states: Dict[str, str], notice: Optional[str], dry_run: bool) -> None:
    """Narrate one project-skills install pass (`new`, `backfill`, `adopt`).

    Outdated and modified skills are named because they are the states an operator may
    want to act on: an outdated copy is pristine and `skills sync` replaces it; a
    modified one is the project's own edit and only `skills sync --force NAME` does.
    """
    if notice:
        console.print(f"[yellow]Notice:[/] {notice}")
        return
    if not states:
        return
    installed = [name for name, state in states.items() if state == INSTALLED]
    updated = [name for name, state in states.items() if state == UPDATED]
    current = [name for name, state in states.items() if state == CURRENT]
    outdated = [name for name, state in states.items() if state == OUTDATED]
    modified = [name for name, state in states.items() if state == MODIFIED]
    if installed:
        verb = "Would install" if dry_run else "Installed"
        console.print(
            f"[cyan]✓ {verb} {len(installed)} project skill(s) in .agents/skills/:[/cyan] "
            + ", ".join(installed)
        )
    if updated:
        verb = "Would update" if dry_run else "Updated"
        console.print(
            f"[cyan]↻ {verb} {len(updated)} project skill(s):[/cyan] " + ", ".join(updated)
        )
    if current:
        console.print(f"[dim]{len(current)} project skill(s) already current[/dim]")
    if outdated:
        console.print(
            "[yellow]Notice:[/] project skill(s) from an earlier release, unmodified: "
            + ", ".join(outdated)
            + ". Run [bold cyan]metaproject skills sync[/bold cyan] to update them."
        )
    if modified:
        console.print(
            "[yellow]Notice:[/] project skill(s) modified locally and left untouched: "
            + ", ".join(modified)
            + ". [bold cyan]metaproject skills sync --force NAME[/bold cyan] discards "
            "local edits."
        )


def print_hooks_report(
    project_dir: Path,
    added: List[str],
    scripts_installed: List[str],
    notice: Optional[str],
    dry_run: bool,
) -> None:
    """Narrate one Claude Code hooks install pass (`new`).

    `added` names the hook events merged into `.claude/settings.json`. When the post-edit
    hook was just wired up but `.metaproject.json` names no command, say so: the hook is
    silent until `commands.lint` (or `commands.typecheck`) is set.
    """
    from metaproject.hooks import SETTINGS_PATH

    if notice:
        console.print(f"[yellow]Notice:[/] {notice}")
        return
    if not added and not scripts_installed:
        return
    verb = "Would add" if dry_run else "Added"
    if added:
        console.print(
            f"[cyan]✓ {verb} metaproject hook(s) to {SETTINGS_PATH}:[/cyan] " + ", ".join(added)
        )
    if scripts_installed:
        script_verb = "would install" if dry_run else "installed"
        console.print(f"[dim]{script_verb} {', '.join(scripts_installed)}[/dim]")
    print_hook_config_hint(project_dir)


def print_hook_config_hint(project_dir: Path) -> None:
    """Say the post-edit hook is idle when `.metaproject.json` names no command."""
    from metaproject.hooks import read_hook_config

    if not read_hook_config(project_dir).has_commands:
        console.print(
            '[dim]The post-edit hook is idle until .metaproject.json sets "commands": '
            '{"lint": "..."} (optionally "typecheck", and "e2e_port" for playwright).[/dim]'
        )


def resolve_project_templates(project_dir: Path, templates_path: Optional[Path]) -> Optional[Path]:
    """Resolve the store once for `backfill`/`adopt`/`review` and say where it came from.

    Resolved once per command and handed on as an explicit path, so a git
    `templates.source` is fetched at most once and every write in the batch renders from
    the same store. The line is printed only when the project declares
    `templates.source`, so output is unchanged for every project that does not.
    """
    from metaproject.template_source import ORIGIN_BUNDLED, resolve_templates

    resolution = resolve_templates(project_dir, templates_path)
    if not resolution.source_declared:
        return templates_path
    style = "yellow" if resolution.origin == ORIGIN_BUNDLED else "dim"
    console.print(f"[{style}]{escape(resolution.describe())}[/{style}]", soft_wrap=True)
    return resolution.path


def print_agent_degradation_notice(what: str, action: str) -> None:
    """Explain a TUI that did not open because an agent is driving.

    Without this the printed board looks like the whole story, and an agent reports
    "nothing to do" when what actually happened is that the interactive half was never
    offered. Silent in a human session, so nothing changes for an operator.
    """
    marker = agent_marker()
    if marker is None:
        return
    console.print(
        f"[dim]Agent session: printed instead of opening {what}. "
        f"To {action}, run this command in your own terminal. {override_hint(marker)}[/dim]"
    )


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
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Accept defaults (and --author) without prompting.",
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help="Default author name (default: git config user.name, never a container "
        "identity such as 'Claude').",
    ),
) -> None:
    """Initialize or repair the user environment for metaproject.

    In the web profile (`CLAUDE_CODE_REMOTE=true` with no config, or
    `METAPROJECT_PROFILE=web`) it writes a minimal config recording `profile: web`,
    never prompts, and skips seeding the template store and the workspace scan.
    """
    target_config_dir = get_config_dir(config_dir)
    config_file = get_config_file_path(target_config_dir)
    web_reason = web_profile_reason(config_file=config_file)

    if web_reason is not None and not (config_file.exists() and not force):
        init_web_profile(target_config_dir, config_file, author, web_reason)
        return

    # If configuration already exists and not forced, display contents and status summary
    if config_file.exists() and not force:
        console.print(f"[bold yellow]Found existing configuration at:[/] {config_file}\n")
        existing_cfg = load_config(config_file)
        console.print(render_config_table(existing_cfg, config_file))

        db_path = Path(existing_cfg.universe_db)
        summary = {
            "total_projects": 0,
            "active_now": 0,
            "last_run": "Never",
            "missing_projects": 0,
        }
        show_summary = web_reason is None
        if show_summary and db_path.exists():
            try:
                summary = get_universe_summary(get_db(db_path))
            except MissingExtraError:
                show_summary = False
        if show_summary:
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

    default_author = (author or "").strip() or existing_cfg.author or detect_git_user_name()
    default_home = (
        str(effective_home.expanduser().resolve()) if effective_home else existing_cfg.project_home
    )

    resolved_home = default_home
    branch = existing_cfg.default_branch

    # If running interactively, prompt for confirmation
    if not force and not non_interactive:
        if not (author or "").strip():
            prompt_author = questionary.text("Default Author Name:", default=default_author).ask()
            if prompt_author:
                default_author = prompt_author.strip()

        prompt_branch = questionary.text("Default Git Branch:", default=branch).ask()
        if prompt_branch:
            branch = prompt_branch.strip()

        prompt_home = questionary.text("Projects Root Directory:", default=resolved_home).ask()
        if prompt_home:
            resolved_home = str(Path(prompt_home).expanduser().resolve())

    universe_db_path = str(target_config_dir / "universe.db")

    new_cfg = Config(
        author=default_author,
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


def init_web_profile(
    target_config_dir: Path, config_file: Path, author: Optional[str], reason: str
) -> None:
    """`init` in the web profile: a minimal config, no store seeding, no scan, no prompt.

    A web container is thrown away after the session, so a catalog of `project_home`
    would describe nothing that outlives it, and `backfill`/`adopt`/`review` already
    fall back to the bundled templates when the store is absent. The config records
    `profile: web` so the profile survives once config exists.
    """
    target_config_dir.mkdir(parents=True, exist_ok=True)
    # Empty lets `Config` detect it; an undetected identity is never persisted.
    cfg = Config(author=(author or "").strip(), profile="web")
    save_config(cfg, config_file)
    console.print(f"[cyan]✓ Saved minimal web-profile configuration to {config_file}[/cyan]")
    console.print(
        f"[dim]Web profile ({reason}): skipped template-store seeding and the workspace "
        "scan; bundled templates are used.[/dim]",
        soft_wrap=True,
    )
    console.print(f"[bold]Author:[/bold] {cfg.author}")


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
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Accept defaults (and --author) without prompting.",
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help="Default author name.",
    ),
) -> None:
    """Alias for 'metaproject init'."""
    init_cmd(
        source_templates=source_templates,
        project_home=project_home,
        project_home_opt=None,
        config_dir=config_dir,
        force=force,
        non_interactive=non_interactive,
        author=author,
    )


def confirm_backfill(target_dir: Path, dry_run: bool, interactive: bool) -> bool:
    """Confirm landing templates into a directory that already holds files.

    Returns True when this may proceed. Non-interactive runs never proceed: the operator
    must either confirm at the prompt or say so up front with --force.

    User-facing text here says "scaffold into an existing directory", never "backfill":
    that word now names one thing, the `metaproject backfill` command, which an agent
    session is pointed at below as the create-only alternative that needs no confirmation.
    """
    entries = list_directory_entries(target_dir)
    preview = ", ".join(entries[:8])
    if len(entries) > 8:
        preview += f", ... (+{len(entries) - 8} more)"

    console.print(
        Panel.fit(
            f"[bold]{target_dir}[/bold] already contains {len(entries)} "
            f"{'entry' if len(entries) == 1 else 'entries'}:\n"
            f"[dim]{preview}[/dim]\n\n"
            f"Scaffolding into an existing directory copies the missing template files "
            f"in alongside them.\n"
            f"[green]Files that already exist are kept as-is, never overwritten.[/green]\n"
            f"[dim]Use --force instead to overwrite colliding files.[/dim]",
            title="[yellow]Scaffold Into an Existing Directory[/yellow]",
        )
    )

    if dry_run:
        marker = agent_marker()
        if marker is not None:
            console.print(
                "[bold yellow]DRY RUN:[/] A real run would ask an operator to confirm "
                "this, and would be refused outright in this agent session (no operator "
                f"to ask). [dim]{override_hint(marker)}[/dim]"
            )
        else:
            console.print("[bold yellow]DRY RUN:[/] A real run would ask you to confirm this.")
        return True

    marker = agent_marker()
    if marker is not None:
        console.print(
            "[bold red]Collision Error:[/bold red] scaffolding into an existing "
            "directory needs an operator's confirmation, and this is an agent session. "
            f"Run [cyan]metaproject new {target_dir}[/cyan] in your own terminal, or "
            f"pass --force to overwrite colliding files. To add missing documents "
            f"without confirmation, run [cyan]metaproject backfill --dir {target_dir}"
            f"[/cyan] instead. [dim]{override_hint(marker)}[/dim]"
        )
        return False

    if not interactive:
        console.print(
            "[bold red]Collision Error:[/bold red] scaffolding into an existing "
            "directory needs confirmation. Re-run without --yes to confirm "
            "interactively, or pass --force to overwrite."
        )
        return False

    answer = questionary.confirm(
        f"Scaffold into {target_dir}, adding the missing template files?",
        default=False,
    ).ask()
    if not answer:
        console.print("[yellow]Aborted:[/] nothing was written.")
        return False
    return True


def confirm_backfill_git(target_dir: Path, interactive: bool) -> bool:
    """Confirm git setup as a decision separate from scaffolding into the directory."""
    if agent_marker() is not None:
        return False

    if is_git_repository(target_dir):
        console.print(
            f"[cyan]Notice:[/] {target_dir} is already a git repository — "
            f"leaving it untouched (no init, no commit)."
        )
        return False

    if not interactive:
        return False

    answer = questionary.confirm(
        f"Also set up git in {target_dir} (init and commit everything currently there)?",
        default=False,
    ).ask()
    if not answer:
        console.print("[cyan]Notice:[/] skipping git setup.")
        return False
    return True


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

    # Backfill: the operator pointed `new` at a directory that already holds work. Landing
    # templates there needs an explicit yes, and wiring up git needs a second one.
    target_dir = resolve_output(output, project_name)
    backfill = not force and not is_directory_empty(target_dir)

    if backfill:
        if not confirm_backfill(target_dir, dry_run=dry_run, interactive=interactive):
            raise typer.Exit(code=1)
        if (
            not dry_run
            and not no_git
            and not confirm_backfill_git(target_dir, interactive=interactive)
        ):
            no_git = True

    try:
        result = scaffold_project(
            project_name=project_name,
            output=output,
            templates_dir=templates,
            title=title,
            description=description,
            author=author,
            # A dry run never prompts, no matter how it is invoked: it previews, it
            # doesn't ask. Without this, variable collection below would still open a
            # questionary prompt during --dry-run, which aborts with no TTY (bug fix).
            interactive=interactive and not dry_run,
            force=force,
            dry_run=dry_run,
            no_git=no_git,
            backfill=backfill,
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
    preserved = result["preserved_files"]
    git_status = result["git_status"]
    warnings = result.get("warnings") or []
    identity_file = result.get("identity_file")

    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    into_existing = result["backfilled"]
    if dry_run:
        target_desc = "the existing directory" if into_existing else "project"
        console.print(
            f"[bold yellow]DRY RUN:[/] Would scaffold {target_desc} at [bold]{target_dir}[/]"
        )
    elif into_existing:
        console.print(
            f"[bold green]Successfully scaffolded into the existing directory:[/] "
            f"[bold]{target_dir}[/]"
        )
    else:
        console.print(f"[bold green]Successfully scaffolded project at:[/] [bold]{target_dir}[/]")

    if identity_file is not None:
        if dry_run:
            console.print("[dim]would write .metaproject.json[/dim]")
        else:
            console.print("[dim]wrote .metaproject.json[/dim]")

    skills_link = result.get("skills_link")
    if dry_run and skills_link is not None:
        console.print(
            f"[dim]would create agent-skills layout: {skills_link.relative_to(target_dir)} "
            f"(-> ../.agents/skills) plus .agents/skills/.gitkeep[/dim]"
        )
    skills_report = result.get("skills")
    if skills_report is not None:
        print_skills_report(skills_report.states, skills_report.notice, dry_run)
    hooks_report = result.get("hooks")
    if hooks_report is not None:
        print_hooks_report(
            target_dir,
            [entry.event for entry in hooks_report.added],
            hooks_report.installed_scripts,
            hooks_report.notice,
            dry_run,
        )

    table = Table(title="Generated Project Files", show_header=True, header_style="bold magenta")
    table.add_column("Relative Path", style="cyan")
    table.add_column("Type", style="green")

    for item in sorted(rendered):
        rel = item.relative_to(target_dir)
        kind = "Directory" if item.is_dir() else "File"
        table.add_row(str(rel), kind)

    console.print(table)

    if preserved:
        kept = Table(title="Kept (Already Present)", show_header=True, header_style="bold magenta")
        kept.add_column("Relative Path", style="cyan")
        for item in sorted(preserved):
            kept.add_row(str(item.relative_to(target_dir)))
        console.print(kept)

    git_summary = {
        "initialized": "Yes (branch main)",
        "existing": "Left existing repository untouched",
        "pending": "Would initialize",
        "skipped": "Skipped",
    }.get(git_status, "Skipped")

    summary = (
        f"[bold]Project Title:[/bold] {variables['ProjectTitle']}\n"
        f"[bold]Author:[/bold] {variables['Author']}\n"
        f"[bold]Date:[/bold] {variables['Date']}\n"
        f"[bold]Git:[/bold] {git_summary}"
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
        help=(
            "Starting scan directory or 'summary' (default: project_home; a path outside"
            " project_home is refused)."
        ),
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
    no_tui: bool = typer.Option(
        False,
        "--no-tui",
        help="Print the table and exit instead of opening the interactive browser.",
    ),
) -> None:
    """Catalog and classify all projects across subdirectories into a SQLite database."""
    import csv
    import io
    import json

    if web_profile_notice("`metaproject universe`", output_format):
        return
    # Every universe path reads or writes the SQLite catalog (the `tui` extra).
    require("sqlite_utils", "`metaproject universe`")

    from metaproject.db import get_db, get_universe_summary
    from metaproject.learn.tui import tui_enabled
    from metaproject.universe import UniverseScopeError, resolve_scan_root, scan_universe

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

    # The interactive browser is the default interface (R-UNV-2): with no positional
    # directory, no display/format flag forcing text, and the same gate as `review`
    # (--no-tui, agent session, TERM=dumb, non-TTY — R-UNV-5), it opens read-only on
    # the DB. Degraded invocations fall through to the scan-then-table path, which is
    # also the printed output for every trigger. Textual is imported lazily so the
    # degraded paths never load it.
    if (
        target_dir is None
        and not list_only
        and not quiet
        and not summary
        and output_format == "table"
        and tui_enabled(no_tui=no_tui)
    ):
        require("textual", "The interactive universe browser")
        from metaproject.universe_tui import run_tui

        run_tui(
            db_path=resolved_db_path,
            project_home=cfg.project_home,
            classification_filter=classification_filter,
            depth=depth,
        )
        return
    if not tui_enabled(no_tui=no_tui):
        print_agent_degradation_notice("the interactive browser", "inspect projects")

    # The scan root is hard-scoped to project_home (R-UNV-1): the configured projects
    # root is the single source of truth for where universe operates. The check runs
    # before the database is opened so a refused path scans and writes nothing.
    try:
        start_path = resolve_scan_root(target_dir, cfg.project_home)
    except UniverseScopeError as exc:
        console.print(f"[red]Refusing to scan:[/red] {exc}")
        raise typer.Exit(1) from exc
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
        1,
        "--depth",
        help="Maximum subdirectory traversal depth for --all (default: 1).",
    ),
    no_tui: bool = typer.Option(
        False,
        "--no-tui",
        help="Print the board and exit instead of opening the interactive actions.",
    ),
    show_ignored: bool = typer.Option(
        False,
        "--show-ignored",
        help="Include projects on the ignore list in the review.",
    ),
    list_ignored: bool = typer.Option(
        False,
        "--list-ignored",
        help="Print the ignore list and exit.",
    ),
    unignore: bool = typer.Option(
        False,
        "--unignore",
        help="Remove the target project from the ignore list and exit.",
    ),
) -> None:
    """Analyze projects against central templates to detect missing files and drift."""
    from metaproject.review import (
        load_ignored,
        review_project,
        review_workspace,
        unignore_project,
    )
    from metaproject.review_tui import run_board
    from metaproject.session import tui_enabled

    target = (project_dir or Path.cwd()).resolve()

    if list_ignored:
        entries = load_ignored()
        if not entries:
            console.print("[dim]No projects are being ignored.[/dim]")
            return
        console.print(Panel("\n".join(entries), title="Ignored projects", border_style="dim"))
        return

    if unignore:
        if unignore_project(target):
            console.print(f"[green]No longer ignored:[/green] {target}")
        else:
            console.print(f"[yellow]{target} was not on the ignore list.[/yellow]")
        return

    if all_projects:
        results = review_workspace(
            target,
            templates_path,
            max_depth=depth,
            include_ignored=show_ignored,
        )
    else:
        templates_path = resolve_project_templates(target, templates_path)
        results = [review_project(target, templates_path)]

    if not results:
        console.print(f"[yellow]No projects discovered for review in {target}[/yellow]")
        return

    # The board leads with the score and what was audited; the scan root and the ignore
    # ledger are this command's knowledge, not the TUI's, so they are handed over.
    ignored_count = len(load_ignored())

    # Warnings are this command's to print (R-TPL-3): the board's own job is the
    # compliance verdict, and a placeholder the store forgot to whitelist is neither
    # missing nor drifted.
    for res in results:
        for warning in res.warnings:
            console.print(f"[yellow]Warning:[/yellow] {res.project_name}: {warning}")

    # Degrades exactly like the `learn` reviewer: --no-tui, an agent session, TERM=dumb,
    # or a non-TTY stdout prints the board and stops, so scripted, CI, and agent use
    # needs no special flag.
    # The web profile never opens the board: it prints the same board `--no-tui` does,
    # after a one-line notice, and exits 0.
    web_board = not no_tui and web_profile_notice(
        "`metaproject review`'s interactive board", instead="printing the board instead"
    )
    if web_board or not tui_enabled(no_tui=no_tui):
        from metaproject.review_tui import review_table

        console.print(review_table(results, target, templates_path, ignored_count))
        if not web_board:
            print_agent_degradation_notice("the interactive board", "remediate drift")
        return

    outcome = run_board(
        results,
        templates_path,
        console=console,
        scan_root=target,
        ignored_count=ignored_count,
    )

    # Printed to the normal screen the alternate screen just restored. `OK 2` on its own
    # was unreadable: the whole point of OK is that it recorded nothing, and a closing
    # line that does not say so invites the operator to read it as Ignore.
    console.print()
    console.print(f"[bold]Review complete[/bold] [dim]·[/dim] {target}")
    console.print(f"  Deployed  {len(outcome.deployed)} missing deliverable(s)")
    console.print(f"  Updated   {len(outcome.updated)} drifted file(s)")
    console.print(
        f"  Ignored   {len(outcome.ignored)} project(s) "
        "[dim]— recorded; not reviewed again until --unignore[/dim]"
    )
    console.print(
        f"  OK        {len(outcome.dismissed)} project(s) "
        "[dim]— this session only; audited again on the next review[/dim]"
    )
    for problem in outcome.errors:
        console.print(f"[red]{problem}[/red]")


def print_backfill_result(result, dry_run: bool, target: Path) -> None:
    """Narrate one `review.backfill_missing` pass (`backfill`, `adopt`)."""
    verb = "Would create" if dry_run else "Created"
    if result.created:
        table = Table(title=verb, show_header=False)
        table.add_column(style="green")
        for path in result.created:
            table.add_row(path)
        console.print(table)

    if result.skipped:
        table = Table(title="Skipped (already exists)", show_header=False)
        table.add_column(style="dim")
        for path in result.skipped:
            table.add_row(path)
        console.print(table)

    from metaproject.hooks import SETTINGS_PATH

    # The settings deliverable is refused for its content (or, when named, an unwritable
    # `.claude/`), never because it "already exists", so it gets its own title.
    existing = [path for path in result.refused if path != SETTINGS_PATH]
    if existing:
        table = Table(title="Refused — already exists, nothing written", show_header=False)
        table.add_column(style="red")
        for path in existing:
            table.add_row(path)
        console.print(table)
    if SETTINGS_PATH in result.refused:
        table = Table(title="Refused — hooks not installed (see notice)", show_header=False)
        table.add_column(style="red")
        table.add_row(SETTINGS_PATH)
        console.print(table)
    if result.not_written:
        table = Table(title="Not written — install yourself (see notice)", show_header=False)
        table.add_column(style="yellow")
        for path in result.not_written:
            table.add_row(path)
        console.print(table)

    if result.missing_template:
        table = Table(title="No template in the store", show_header=False)
        table.add_column(style="red")
        for path in result.missing_template:
            table.add_row(path)
        console.print(table)

    print_skills_report(result.skills, result.skills_notice, dry_run)
    if result.hooks_notice:
        console.print(f"[yellow]Notice:[/] {result.hooks_notice}")
    elif ".claude/settings.json" in result.created:
        print_hook_config_hint(target)

    wrote_skills = any(state == INSTALLED for state in result.skills.values())
    if not (
        result.created
        or result.skipped
        or result.refused
        or result.not_written
        or result.missing_template
        or wrote_skills
    ):
        console.print("[dim]Nothing to do.[/dim]")


@app.command(name="backfill")
def backfill_cmd(
    files: Optional[List[str]] = typer.Argument(
        None,
        help="Specific deliverables to create (e.g. docs/HANDOFF.md; old names such as "
        "intent.md resolve to their docs/ path). Default: every "
        "missing deliverable `new` scaffolds.",
    ),
    project_dir: Optional[Path] = typer.Option(
        None,
        "--dir",
        "-d",
        help="Project directory to backfill (default: current directory).",
    ),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Template directory to create from (default: ~/.metaproject/templates).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview what would be created without writing to disk.",
    ),
) -> None:
    """Create missing deliverables from the template store. Never overwrites, never runs git.

    Unlike `new .`, this is a non-interactive, create-only write and is permitted in
    agent sessions (R-TPL-8): it is how a skill or hook fills in a document that review
    reports missing, without the confirmations `new .` requires.
    """
    from metaproject.review import backfill_missing

    target = (project_dir or Path.cwd()).resolve()
    templates_path = resolve_project_templates(target, templates_path)
    result = backfill_missing(
        target, files=files or None, templates_dir=templates_path, dry_run=dry_run
    )

    print_backfill_result(result, dry_run, target)
    if result.refused or result.missing_template:
        raise typer.Exit(code=1)


@app.command(name="adopt")
def adopt_cmd(
    project_dir: Optional[Path] = typer.Option(
        None,
        "--dir",
        "-d",
        help="Repository to adopt (default: current directory).",
    ),
    title: Optional[str] = typer.Option(
        None,
        "--title",
        help="Project title (default: README heading, manifest name, or directory name).",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        help="One-line summary (default: the paragraph under the README heading).",
    ),
    author: Optional[str] = typer.Option(
        None,
        "--author",
        "-a",
        help="Author (default: config, then git config user.name; never 'Claude').",
    ),
    templates_path: Optional[Path] = typer.Option(
        None,
        "--templates",
        help="Template directory to create from (default: ~/.metaproject/templates).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview what would be created without writing to disk.",
    ),
) -> None:
    """Adopt an existing repository. Create-only, runs no git, needs no confirmation.

    Writes `.metaproject.json`, the `.agents/skills` layout, every missing deliverable
    and every missing project skill. Nothing that exists is overwritten, so it is the
    agent-safe way to bring an already-cloned repository under metaproject (permitted
    in agent sessions). `new .` keeps its interactive, operator-confirmed semantics.
    """
    from metaproject.scaffold import adopt_project

    target = (project_dir or Path.cwd()).resolve()
    templates_path = resolve_project_templates(target, templates_path)
    try:
        result = adopt_project(
            target,
            title=title,
            description=description,
            author=author,
            templates_dir=templates_path,
            dry_run=dry_run,
        )
    except MetaProjectError as exc:
        console.print(f"[bold red]Adopt Error:[/bold red] {exc}", soft_wrap=True)
        raise typer.Exit(code=1)

    verb = "Would adopt" if dry_run else "Adopted"
    console.print(f"[bold green]{verb}:[/bold green] [bold]{result.target_dir}[/bold]")
    if result.identity_written:
        action = "would write" if dry_run else "wrote"
        console.print(
            f"[dim]{action} .metaproject.json[/dim] "
            f"(title: {result.identity.title}, author: {result.identity.author})",
            soft_wrap=True,
        )
    else:
        console.print("[dim].metaproject.json already present — kept as-is[/dim]")
    if result.skills_link is not None:
        action = "would create" if dry_run else "created"
        console.print(f"[dim]{action} .claude/skills -> ../.agents/skills[/dim]")

    print_backfill_result(result.backfill, dry_run, target)
    if result.backfill.missing_template:
        raise typer.Exit(code=1)


@app.command(name="doctor")
def doctor_cmd(
    project: Optional[Path] = typer.Argument(
        None,
        help=(
            "Operate on this one project — its anchor, cycle documents, and skills — "
            "instead of the whole environment (e.g. `metaproject doctor .`)."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report findings and the fixes that would apply, without prompting or writing.",
    ),
) -> None:
    """Diagnose and repair a stale installed environment after an upgrade.

    Without a project, checks, in order: the template store's layout (cycle templates
    still at its root), the template store, `learn.targets` in config.json, an orphaned
    `~/.claude/skills/metaproject/` from older releases, per-project
    `.metaproject.json` anchors, and — per cataloged, metaproject-managed project —
    cycle documents at their old root locations and missing or stale project skills.
    With a PROJECT path, only that project is examined — its anchor, its cycle
    documents, its skills — and the environment-wide checks are skipped. Each fix
    needs an operator's confirmation (per project for the project checks);
    `--dry-run` writes nothing and is the only form permitted inside an agent session.

    In the web profile the environment-wide checks (store layout, store, config,
    orphaned global skill, the catalog) are skipped with a one-line notice — none of
    them outlives a web container — and the per-project checks (identity, docs,
    skills) run against PROJECT when given, else the current directory — the one
    project the session has.
    """
    from metaproject import doctor

    if project is not None:
        project = project.resolve()
        if not project.is_dir():
            console.print(
                Panel.fit(
                    f"Not a directory: [cyan]{project}[/cyan]\n\n"
                    "Doctor's project checks repair a project's directory.",
                    title="[red]Bad Project Path[/red]",
                )
            )
            raise typer.Exit(code=1)

    # In the web profile the environment-wide checks have nothing to act on; the
    # project checks still run — against an explicit PROJECT, else the current
    # directory, the one project the session has.
    web = web_profile_notice(
        "Running `metaproject doctor`'s store, config and catalog checks",
        instead="running the project checks only",
    )
    if web and project is None:
        project = Path.cwd().resolve()

    # The web profile has no operator to refuse on behalf of: an agent session (or a
    # core install without questionary to confirm with) degrades to the report
    # `--dry-run` prints rather than a refusal. Its exit code is the report's: 0 for a
    # healthy project, 1 when there are findings.
    if web and not dry_run:
        marker = agent_marker()
        if marker is not None or not available("questionary"):
            why = (
                f"{marker} is set"
                if marker is not None
                else f"questionary is not installed: {escape(INSTALL_HINT)}"
            )
            console.print(
                "[yellow]Notice:[/] doctor's fixes need an operator to confirm them; "
                f"reporting findings only, as --dry-run would ({why}).",
                soft_wrap=True,
            )
            dry_run = True

    if not dry_run:
        marker = agent_marker()
        if marker is not None:
            console.print(
                Panel.fit(
                    "[bold]`metaproject doctor` needs an operator.[/bold]\n\n"
                    "Its fixes write to the template store, your config, ~/.claude,\n"
                    "and other projects — decisions that are the operator's\n"
                    "to make, not an agent's.\n\n"
                    "[bold]Preview the findings instead:[/bold]\n"
                    "  [cyan]metaproject doctor --dry-run[/cyan]\n\n"
                    f"[dim]{override_hint(marker)}[/dim]",
                    title="[yellow]Agent Session — Doctor Refused[/yellow]",
                )
            )
            raise typer.Exit(code=1)

    config_file = get_config_file_path()
    if web:
        # A web container may never have run `init`; the project checks need no config.
        cfg = load_config(config_file) if config_file.exists() else Config(profile="web")
    elif not config_file.exists():
        console.print(
            Panel.fit(
                f"No configuration found at [cyan]{config_file}[/cyan].\n\n"
                "Run [cyan]metaproject init[/cyan] first; doctor repairs an\n"
                "initialized environment, it doesn't create one.",
                title="[red]Not Initialized[/red]",
            )
        )
        raise typer.Exit(code=1)
    else:
        cfg = load_config(config_file)
    results = doctor.run_checks(cfg, config_file, dry_run=dry_run, project=project)

    title = f"Doctor — {project}" if project is not None else "Doctor — Environment Health"
    table = Table(title=title)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for result in results:
        if result.healthy and not result.findings:
            status = "[green]healthy[/green]"
        elif result.fixed and result.report_only:
            status = "[yellow]fixed; needs attention[/yellow]"
        elif result.fixed:
            status = "[green]fixed[/green]"
        elif result.healthy:
            status = "[green]healthy[/green]"
        elif result.report_only and set(result.findings) <= set(result.report_only):
            status = "[yellow]needs attention[/yellow]"
        elif result.fixed is None and dry_run:
            status = "[yellow]would fix[/yellow]" if result.findings else "[green]healthy[/green]"
        else:
            status = "[red]stale (declined)[/red]"
        detail = "\n".join(result.findings) if result.findings else "—"
        fixable = not set(result.findings) <= set(result.report_only)
        if result.findings and fixable and not (result.healthy and not result.fixed):
            detail += f"\n[dim]fix: {result.fix_summary}[/dim]"
        table.add_row(result.name, status, detail)
    console.print(table)

    if not all(result.healthy for result in results):
        raise typer.Exit(code=1)


# -------------------------------------------------------------------------- skills
#
# `skills status` and `skills sync` are agent-safe: no agent guard, no prompt, no config
# or template store, and not behind the web profile. They act on one project's
# `.agents/skills` and nothing else.

skills_app = typer.Typer(
    name="skills",
    help=(
        "Inspect and update this project's bundled skills (agent-safe).\n\n"
        "Each skill is current, outdated (a pristine copy of an earlier release), "
        "modified (local edits) or missing. `sync` installs missing skills and replaces "
        "outdated ones; a modified skill is replaced only when named with --force."
    ),
    no_args_is_help=True,
)
app.add_typer(skills_app, name="skills")

SKILL_STATE_LABELS = {
    "current": "[green]✓ current[/green]",
    "outdated": "[yellow]↻ outdated[/yellow]",
    "modified": "[magenta]~ modified[/magenta]",
    "missing": "[red]! missing[/red]",
}
SKILL_ACTION_LABELS = {
    "installed": "installed",
    "updated": "updated",
    "forced": "replaced (--force)",
    "kept": "kept",
    "recorded": "kept (manifest recorded)",
}


def _skills_console(output_format: str) -> Console:
    """Diagnostics go to stderr under `--format json`, so stdout stays pure JSON."""
    return Console(stderr=True) if output_format == "json" else console


def _skills_project(project_dir: Optional[Path], output_format: str) -> Path:
    """The managed project to act on, or exit 1 with the reason."""
    from metaproject.identity import IDENTITY_FILE

    out = _skills_console(output_format)
    if output_format not in ("table", "json"):
        out.print(f"[bold red]Error:[/bold red] unknown --format {output_format!r}")
        raise typer.Exit(code=1)
    target = (project_dir or Path.cwd()).resolve()
    if not target.is_dir():
        out.print(f"[bold red]Error:[/bold red] {target} is not a directory.", soft_wrap=True)
        raise typer.Exit(code=1)
    if not (target / IDENTITY_FILE).is_file():
        out.print(
            f"[bold red]Error:[/bold red] no {IDENTITY_FILE} in {target}; run "
            "[bold cyan]metaproject adopt[/bold cyan] first.",
            soft_wrap=True,
        )
        raise typer.Exit(code=1)
    return target


def _skills_payload(project: Path, report, dry_run: bool, with_action: bool) -> Dict[str, Any]:
    from metaproject.skills import running_release

    try:
        target = report.target.relative_to(project).as_posix()
    except ValueError:
        target = str(report.target)
    return {
        "project": str(project),
        "target": target,
        "release": running_release(),
        "manifest": report.manifest_state,
        "refusal": report.notice,
        "dry_run": dry_run,
        "skills": [
            {
                "name": status.name,
                "state": status.state,
                "installed_release": status.installed_release,
                "basis": status.basis,
                "changed": list(status.changed),
                "note": status.note,
                "action": status.action if with_action else None,
            }
            for status in report.statuses
        ],
    }


def _skill_detail(status) -> str:
    if status.note:
        return escape(status.note)
    if status.state in ("outdated", "modified") and status.changed:
        shown = ", ".join(status.changed[:3])
        more = f" (+{len(status.changed) - 3} more)" if len(status.changed) > 3 else ""
        return escape(f"differs: {shown}{more}")
    return "—"


def _render_skills_report(
    project: Path, report, output_format: str, dry_run: bool, with_action: bool
) -> None:
    """Print one status/sync report; exit 1 on a refusal."""
    import json

    out = _skills_console(output_format)
    if output_format == "json":
        typer.echo(json.dumps(_skills_payload(project, report, dry_run, with_action), indent=2))
    for warning in report.warnings:
        out.print(f"[yellow]Notice:[/] {escape(warning)}", soft_wrap=True)
    if report.notice:
        out.print(f"[yellow]Refused:[/] {escape(report.notice)}", soft_wrap=True)
        raise typer.Exit(code=1)
    if output_format == "json":
        return
    title = f"Project skills — {project}"
    if dry_run:
        title += " (dry run)"
    table = Table(title=escape(title), show_header=True, header_style="bold magenta")
    table.add_column("Skill", style="bold cyan")
    table.add_column("State")
    table.add_column("Installed release")
    if with_action:
        table.add_column("Action")
    table.add_column("Detail")
    for status in report.statuses:
        row = [
            status.name,
            SKILL_STATE_LABELS.get(status.state, status.state),
            status.installed_release or "—",
        ]
        if with_action:
            row.append(SKILL_ACTION_LABELS.get(status.action or "", status.action or "—"))
        row.append(_skill_detail(status))
        table.add_row(*row)
    console.print(table)
    modified = [s.name for s in report.statuses if s.state == "modified" and s.action != "forced"]
    if modified:
        console.print(
            "[yellow]Notice:[/] modified skill(s) left untouched: "
            + ", ".join(modified)
            + ". [bold cyan]metaproject skills sync --force NAME[/bold cyan] discards local "
            "edits.",
            soft_wrap=True,
        )
    outdated = [s.name for s in report.statuses if s.state == "outdated" and s.action is None]
    if outdated:
        console.print(
            "[yellow]Notice:[/] outdated skill(s): "
            + ", ".join(outdated)
            + ". Run [bold cyan]metaproject skills sync[/bold cyan] to update them.",
            soft_wrap=True,
        )


@skills_app.command(name="status")
def skills_status_cmd(
    project_dir: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project to inspect (default: current directory)."
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table or json."
    ),
) -> None:
    """Report each bundled skill as current, outdated, modified or missing. Read-only."""
    from metaproject.skills import inspect_project_skills

    project = _skills_project(project_dir, output_format)
    report = inspect_project_skills(project)
    _render_skills_report(project, report, output_format, dry_run=False, with_action=False)


@skills_app.command(name="sync")
def skills_sync_cmd(
    project_dir: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project to sync (default: current directory)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would change without writing anything."
    ),
    force: Optional[List[str]] = typer.Option(
        None,
        "--force",
        help="Replace this skill even if modified (discards local edits). Repeatable.",
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table or json."
    ),
) -> None:
    """Install missing skills and update outdated, unmodified ones.

    A modified skill is kept and reported (exit 0) unless named with `--force NAME`.
    Each replacement is atomic per skill and recorded in
    .agents/skills/.metaproject-skills.json.
    """
    from metaproject.skills import sync_project_skills

    project = _skills_project(project_dir, output_format)
    out = _skills_console(output_format)
    try:
        report = sync_project_skills(
            project, update=True, force=tuple(force or ()), dry_run=dry_run
        )
    except MetaProjectError as exc:
        out.print(f"[bold red]Skills Error:[/bold red] {escape(str(exc))}", soft_wrap=True)
        raise typer.Exit(code=1)
    _render_skills_report(project, report, output_format, dry_run=dry_run, with_action=True)
    claude_skills = project / ".claude" / "skills"
    if not claude_skills.exists() and not claude_skills.is_symlink():
        out.print(
            "[yellow]Notice:[/] .claude/skills is absent, so Claude Code will not see these "
            "skills; run [bold cyan]metaproject adopt[/bold cyan] to create the link.",
            soft_wrap=True,
        )


# ----------------------------------------------------------------------- templates

templates_app = typer.Typer(
    name="templates",
    help=(
        "Work with a project's declared template store (agent-safe).\n\n"
        'A project may declare `"templates": {"source": ...}` in .metaproject.json — a '
        "git URL (optionally with ref and subdir) or a path in the repository. When "
        "~/.metaproject/templates is missing, backfill, adopt and review render from it."
    ),
    no_args_is_help=True,
)
app.add_typer(templates_app, name="templates")


@templates_app.command(name="fetch")
def templates_fetch_cmd(
    project_dir: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Project whose templates.source to fetch (default: cwd)."
    ),
) -> None:
    """Shallow-fetch (or refresh) the project's git `templates.source` into the cache.

    A no-op that exits 0 when the project declares no source. A path source is checked,
    not copied. Exits 1 when the source is malformed or cannot be fetched; a cache from
    an earlier fetch is kept and still used.
    """
    from metaproject.template_source import (
        TemplateSourceError,
        fetch_template_source,
        read_template_source,
        store_usable,
    )

    target = (project_dir or Path.cwd()).resolve()
    try:
        source = read_template_source(target)
    except TemplateSourceError as exc:
        console.print(f"[bold red]Error:[/bold red] {escape(str(exc))}", soft_wrap=True)
        raise typer.Exit(code=1)
    if source is None:
        console.print("[dim]No templates.source in .metaproject.json; nothing to fetch.[/dim]")
        return
    if source.kind == "path":
        path = (target / Path(source.location).expanduser()).resolve()
        if store_usable(path):
            console.print(f"[green]✓[/green] templates.source is a path: {path}", soft_wrap=True)
            return
        console.print(
            f"[bold red]Error:[/bold red] templates.source path {path} is missing or empty.",
            soft_wrap=True,
        )
        raise typer.Exit(code=1)

    result = fetch_template_source(source)
    if result.ok:
        console.print(f"[green]✓[/green] {escape(result.message)} → {result.path}", soft_wrap=True)
        return
    color = "yellow" if result.path is not None else "bold red"
    console.print(
        f"[{color}]Could not fetch {escape(source.label)}:[/{color}] {escape(result.message)}",
        soft_wrap=True,
    )
    raise typer.Exit(code=1)


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

    def invoke(self, ctx):
        # One gate for every `learn` subcommand: the web profile has no catalog or
        # store to learn from, and the ledger lives in SQLite (the `tui` extra).
        if web_profile_notice("`metaproject learn`"):
            return None
        require("sqlite_utils", "`metaproject learn`")
        return super().invoke(ctx)


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


def rebuild_scan_command(
    target: Path,
    all_projects: bool,
    depth: int,
    since: Optional[str],
    model: Optional[str],
    templates_dir: Path,
) -> str:
    """Reconstruct the `learn scan` invocation so the operator can run it verbatim."""
    parts = ["metaproject", "learn", "scan"]
    if all_projects:
        parts.append("--all")
    else:
        # Absolute, because the operator may paste this from a different directory.
        parts.append(str(target.expanduser().resolve()))
    if depth != 4:
        parts.extend(["--depth", str(depth)])
    if since:
        parts.extend(["--since", since])
    if model:
        parts.extend(["--model", model])
    if templates_dir != Path(load_config().templates_dir).expanduser().resolve():
        parts.extend(["--templates", str(templates_dir)])
    return " ".join(parts)


def refuse_scan_in_agent_session(
    target: Path,
    all_projects: bool,
    depth: int,
    since: Optional[str],
    model: Optional[str],
    templates_dir: Path,
) -> None:
    """Stop a scan an agent started, and say what to do instead.

    A scan reads every project, calls a model, and sends redacted diffs off the machine.
    Spending an operator's money and egressing their code is their decision to make, and
    an agent that wants one should surface the command rather than run it. The refusal
    hands over the exact invocation and points at the proposals already on disk, so the
    agent has something useful to do either way.
    """
    marker = agent_marker()
    if marker is None:
        return

    command = rebuild_scan_command(target, all_projects, depth, since, model, templates_dir)
    console.print(
        Panel.fit(
            "[bold]`learn scan` needs an operator.[/bold]\n\n"
            "It reads every project under the scan root, calls a model, and sends\n"
            "redacted diffs off this machine — a decision that is the operator's to\n"
            "make, not an agent's.\n\n"
            "[bold]Hand them this command:[/bold]\n"
            f"  [cyan]{command}[/cyan]\n\n"
            "Proposals already recorded are readable right now:\n"
            "  [cyan]metaproject learn list[/cyan]\n"
            "  [cyan]metaproject learn show <id>[/cyan]\n\n"
            f"[dim]{override_hint(marker)}[/dim]",
            title="[yellow]Agent Session — Scan Refused[/yellow]",
        )
    )
    raise typer.Exit(code=1)


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

    refuse_scan_in_agent_session(
        target=target,
        all_projects=all_projects,
        depth=depth,
        since=since,
        model=model,
        templates_dir=templates_dir,
    )

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
        print_agent_degradation_notice("the acceptance reviewer", "accept a proposal")
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
