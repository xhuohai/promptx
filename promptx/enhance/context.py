from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..repo import Repository


IGNORED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "coverage",
    "__pycache__",
}

PROJECT_MARKERS = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "setup.py": "Python",
    "package.json": "JavaScript/TypeScript",
    "tsconfig.json": "TypeScript",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java/Maven",
    "build.gradle": "Java/Gradle",
    "build.gradle.kts": "Kotlin/Gradle",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Package.swift": "Swift",
    "CMakeLists.txt": "C/C++",
}

FRAMEWORK_MARKERS = {
    "django": "Django",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "pytest": "pytest",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
    "express": "Express",
    "nestjs": "NestJS",
    "spring-boot": "Spring Boot",
    "rails": "Rails",
}

KEY_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "README.rst",
    "README.txt",
    "Makefile",
    "justfile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".promptx.toml",
    *PROJECT_MARKERS.keys(),
}

TEXT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html",
    ".java", ".js", ".json", ".jsx", ".kt", ".kts", ".md", ".php",
    ".py", ".rb", ".rs", ".sh", ".sql", ".swift", ".toml", ".ts",
    ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "hello", "i", "in", "is", "it", "of", "on", "or", "please", "that", "the",
    "this", "to", "with", "you", "一下", "一个", "不要", "为什么", "什么", "可以",
    "实现", "帮我", "我们", "看看", "相关", "这个", "这里", "还是", "进行",
}

TASK_PATTERNS = {
    "debug": ("bug", "crash", "deadlock", "error", "fail", "fix", "hang", "修复", "报错", "失败", "死锁"),
    "test": ("coverage", "spec", "test", "pytest", "测试", "用例"),
    "refactor": ("cleanup", "refactor", "restructure", "重构", "整理"),
    "review": ("audit", "review", "security", "审查", "评审", "安全"),
    "explain": ("explain", "how", "why", "解释", "为什么", "原理"),
    "implement": ("add", "build", "create", "implement", "support", "增加", "实现", "新增", "支持"),
}


@dataclass(frozen=True)
class Candidate:
    path: str
    score: int
    evidence: str


@dataclass(frozen=True)
class WorkspaceContext:
    task_type: str
    keywords: tuple[str, ...]
    stack: tuple[str, ...]
    markers: tuple[str, ...]
    tree: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    git_branch: str
    git_status: tuple[str, ...]
    git_diff: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"Task type: {self.task_type}",
            f"Keywords: {', '.join(self.keywords) if self.keywords else '-'}",
            f"Detected stack: {', '.join(self.stack) if self.stack else 'unknown'}",
            f"Project markers: {', '.join(self.markers) if self.markers else '-'}",
            f"Git branch: {self.git_branch or '-'}",
            "Git status:",
            *([f"  {item}" for item in self.git_status] or ["  clean or unavailable"]),
            "Git diff summary:",
            *([f"  {item}" for item in self.git_diff] or ["  none or unavailable"]),
            "Workspace tree:",
            *([f"  {item}" for item in self.tree] or ["  (empty)"]),
            "Candidate files (hints, not verified task facts):",
            *(
                [f"  {item.path} [score={item.score}; {item.evidence}]" for item in self.candidates]
                or ["  (none)"]
            ),
        ]
        return "\n".join(lines)


def _task_type(prompt: str) -> str:
    lowered = prompt.casefold()
    scores = {
        name: sum(1 for term in terms if term in lowered)
        for name, terms in TASK_PATTERNS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"


def _keywords(prompt: str) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.:/-]{1,}|[\u3400-\u9fff]{2,}", prompt)
    result: list[str] = []
    for token in tokens:
        normalized = token.casefold()
        if normalized in STOP_WORDS or normalized in result:
            continue
        result.append(normalized)
    return tuple(result[:12])


def _walk(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRECTORIES and not name.startswith(".promptx-")
        )
        for name in sorted(names):
            path = Path(current) / name
            try:
                if path.is_symlink() or path.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            files.append(path)
            if len(files) >= 1500:
                return files
    return files


def _tree(root: Path, files: list[Path]) -> tuple[str, ...]:
    values: set[str] = set()
    for path in files:
        relative = path.relative_to(root)
        if len(relative.parts) > 4:
            continue
        values.add(relative.as_posix())
    return tuple(sorted(values)[:120])


def _content_hits(path: Path, keywords: tuple[str, ...]) -> tuple[int, str]:
    if not keywords or (path.suffix.lower() not in TEXT_SUFFIXES and path.name not in KEY_FILES):
        return 0, "path/key-file match"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")[:120_000].casefold()
    except OSError:
        return 0, "path/key-file match"
    hits = [keyword for keyword in keywords if keyword in text]
    if not hits:
        return 0, "path/key-file match"
    return min(len(hits), 4) * 2, "content: " + ", ".join(hits[:4])


def _candidates(root: Path, files: list[Path], keywords: tuple[str, ...]) -> tuple[Candidate, ...]:
    ranked: list[Candidate] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        lowered = relative.casefold()
        score = 3 if path.name in KEY_FILES else 0
        path_hits = [keyword for keyword in keywords if keyword in lowered]
        score += len(path_hits) * 5
        content_score, evidence = _content_hits(path, keywords)
        score += content_score
        if path_hits:
            evidence = "path: " + ", ".join(path_hits[:4])
        if score:
            ranked.append(Candidate(relative, score, evidence))
    ranked.sort(key=lambda item: (-item.score, len(item.path), item.path))
    return tuple(ranked[:12])


def _project_facts(root: Path, files: list[Path]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    marker_paths = [
        path for path in files if path.name in PROJECT_MARKERS
    ]
    markers = tuple(path.relative_to(root).as_posix() for path in marker_paths[:30])
    detected = [PROJECT_MARKERS[path.name] for path in marker_paths]
    for path in marker_paths:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:200_000].casefold()
        except OSError:
            continue
        for token, label in FRAMEWORK_MARKERS.items():
            if re.search(rf"(?<![a-z0-9_-]){re.escape(token)}(?![a-z0-9_-])", content):
                detected.append(label)
    return markers, tuple(dict.fromkeys(detected))


def _git(repo: Repository, *args: str) -> str:
    if not repo.is_git:
        return ""
    process = subprocess.run(
        ["git", *args], cwd=repo.root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=False, timeout=5,
    )
    return process.stdout.strip() if process.returncode == 0 else ""


def collect_context(prompt: str, repo: Repository) -> WorkspaceContext:
    files = _walk(repo.root)
    markers, stack = _project_facts(repo.root, files)
    keywords = _keywords(prompt)
    status = tuple(_git(repo, "status", "--short").splitlines()[:40])
    return WorkspaceContext(
        task_type=_task_type(prompt),
        keywords=keywords,
        stack=stack,
        markers=markers,
        tree=_tree(repo.root, files),
        candidates=_candidates(repo.root, files, keywords),
        git_branch=_git(repo, "branch", "--show-current"),
        git_status=status,
        git_diff=tuple(_git(repo, "diff", "--stat", "HEAD").splitlines()[:40]),
    )
