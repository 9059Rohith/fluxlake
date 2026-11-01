"""One small code-native, currentColor thin-line icon family for the observatory."""

PATHS = {
    "overview": '<path d="M5 20V12m7 8V4m7 16V8"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    "upload": '<path d="M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6"/>',
    "archive": '<rect x="4" y="7" width="16" height="14" rx="2"/><path d="M3 3h18v4H3zm6 8h6"/>',
    "layers": '<path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',
    "file": '<path d="M5 2h9l5 5v15H5zM14 2v6h5M8 12h8m-8 4h6"/>',
    "activity": '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    "warning": '<path d="m12 3 10 18H2ZM12 9v5m0 3v1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    "lineage": '<circle cx="12" cy="4" r="2"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/><path d="M12 6v5m0 0-8 4v3m8-7 8 4v3"/>',
    "message": '<path d="M21 16a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "arrow": '<path d="M3 12h18m-6-6 6 6-6 6"/>',
    "external": '<path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6"/>',
    "chevron": '<path d="m9 5 7 7-7 7"/>',
    "refresh": '<path d="M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5m-4 8a8 8 0 0 0 14 3l3-3m0 5v-5h-5"/>',
    "close": '<path d="m5 5 14 14M19 5 5 19"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "download": '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    "shield": '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Zm-4 10 3 3 5-6"/>',
    "user": '<circle cx="12" cy="7" r="4"/><path d="M3 22v-4c0-6 18-6 18 0v4"/>',
    "users": '<circle cx="9" cy="7" r="3"/><path d="M2 21v-4c0-5 14-5 14 0v4m1-17a3 3 0 0 1 0 6m2 4c3 0 3 3 3 6"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "check": '<path d="m4 12 5 5L20 6"/>',
    "sort": '<path d="M8 4v16m-4-4 4 4 4-4m4-12v16m-4-16 4-4 4 4"/>',
    "github": '<path d="M9 20c-4 1-4-2-6-2m12 4v-4c0-1 .2-2-1-3 4-.5 7-2 7-6 0-2-1-3-2-4 0-1 0-2-1-3-2 0-3 1-4 2a13 13 0 0 0-5 0C8 3 7 2 5 2 4 3 4 5 4 6 3 7 2 8 2 10c0 4 3 6 7 6-1 1-1 2-1 3v3"/>',
}


def icon(name):
    return f'<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><use href="/assets/icons.svg#{name}"/></svg>'


def sprite():
    symbols = "".join(
        f'<symbol id="{name}" viewBox="0 0 24 24">{paths}</symbol>' for name, paths in PATHS.items()
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{symbols}</svg>'
