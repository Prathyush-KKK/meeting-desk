"""The demo world: a fictional team, its meetings, notes and roadmap workbooks.

It is the single source of demo data: the fake Google builds its calendar, Drive, Docs, Gmail and
Sheets from it, and ``app/bootstrap.py`` writes the same rows into the database so a local run and
the tests see one consistent world.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from app.tz import display_zone

PEOPLE: list[dict[str, str]] = [
    {"name": "Alex S", "email": "alex.s@example.com"},
    {"name": "Daniel Okafor", "email": "daniel.okafor@example.com"},
    {"name": "Daniela Mehta", "email": "daniela.mehta@example.com"},
    {"name": "Noah S", "email": "noah.s@example.com"},
    {"name": "Anna Moreno", "email": "anna.moreno@example.com"},
    {"name": "Sofia Silva", "email": "sofia.silva@example.com"},
    {"name": "Aiden Murphy", "email": "aiden.murphy@example.com"},
]

# Two people whose first names collide - the spec's ambiguity case.
DIRECTORY: list[dict[str, str]] = [
    *PEOPLE,
    {"name": "Maya Rao", "email": "maya.rao@northwind.example"},
    {"name": "Ethan Verma", "email": "ethan.verma@candidate.example"},
]

ALIASES: dict[str, str] = {
    "dan": "daniel.okafor@example.com",
    "alex": "alex.s@example.com",
    "sofia": "sofia.silva@example.com",
}

WORKSTREAMS = ["Mobile", "Platform", "Billing", "Rewards", "Prod ops", "Hiring"]

DEMO_USER = "daniel.okafor@example.com"

CONNECTIONS: list[dict[str, Any]] = [
    {
        "email": "daniel.okafor@example.com",
        "name": "Daniel Okafor",
        "scopes": [
            "calendar.readonly",
            "drive.readonly",
            "documents.readonly",
            "gmail.readonly",
            "spreadsheets",
        ],
        "connected_at": "2026-09-21T08:32:00+00:00",
        "status": "ok",
    },
    {
        "email": "alex.s@example.com",
        "name": "Alex S",
        "scopes": ["calendar.readonly", "drive.readonly", "spreadsheets"],
        "connected_at": "2026-09-21T13:00:00+00:00",
        "status": "ok",
    },
]

ALLOW_LIST: list[dict[str, str]] = [
    {"email": "daniel.okafor@example.com", "role": "admin", "added_by": "setup"},
    {"email": "alex.s@example.com", "role": "admin", "added_by": "daniel.okafor@example.com"},
    {"email": "noah.s@example.com", "role": "member", "added_by": "daniel.okafor@example.com"},
    {
        "email": "daniela.mehta@example.com",
        "role": "member",
        "added_by": "daniel.okafor@example.com",
    },
    {"email": "anna.moreno@example.com", "role": "member", "added_by": "alex.s@example.com"},
]


def person(name_or_email: str) -> dict[str, str]:
    for p in PEOPLE:
        if name_or_email in (p["name"], p["email"]):
            return p
    return {"name": name_or_email, "email": name_or_email.lower().replace(" ", ".") + "@example.com"}


def attendees(names: list[str], responses: list[str] | None = None) -> list[dict[str, str]]:
    out = []
    for i, n in enumerate(names):
        p = person(n)
        out.append(
            {
                "name": p["name"],
                "email": p["email"],
                "response": responses[i] if responses and i < len(responses) else "accepted",
            }
        )
    return out


def at(day: str, hhmm: str) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    h, mi = (int(x) for x in hhmm.split(":"))
    return datetime.combine(date(y, m, d), time(h, mi), tzinfo=display_zone())


MEETINGS: list[dict[str, Any]] = [
    {
        "ref": "m1",
        "key": "M-118",
        "source": "calendar",
        "title": "Platform squad sync",
        "date": "2026-09-22",
        "start": "16:00",
        "end": "16:48",
        "organizer": "alex.s@example.com",
        "attendees": attendees(
            ["Alex S", "Daniel Okafor", "Daniela Mehta", "Noah S"],
            ["accepted", "accepted", "accepted", "tentative"],
        ),
        "description": "Weekly platform squad sync: upload unification, telemetry, payments, compliance.",
        "location": "",
        "meet_link": "meet.google.com/pls-quad-snc",
        "recurring": "Weekly on Tuesday",
        "attachments": [
            {"title": "Notes by Gemini", "kind": "doc"},
            {"title": "Transcript", "kind": "transcript"},
        ],
        "calendar_event_id": "platformsync0demo0event01",
        "workstream": "Platform",
        "step": "meeting",
    },
    {
        "ref": "m2",
        "key": "M-117",
        "source": "calendar",
        "title": "Mobile roadmap review",
        "date": "2026-09-19",
        "start": "11:00",
        "end": "12:10",
        "organizer": "daniel.okafor@example.com",
        "attendees": attendees(
            ["Daniel Okafor", "Anna Moreno", "Noah S", "Sofia Silva", "Alex S"]
        ),
        "description": "Compare expense features against competitors; refine AI receipt analysis workflows.",
        "location": "",
        "meet_link": "meet.google.com/mob-road-rev",
        "recurring": "",
        "attachments": [],
        "calendar_event_id": "mob19sep",
        "workstream": "Mobile",
        "step": "points",
    },
    {
        "ref": "m3",
        "key": "M-116",
        "source": "manual",
        "title": "Northwind call prep",
        "date": "2026-09-18",
        "start": "15:00",
        "end": "15:30",
        "organizer": "alex.s@example.com",
        "attendees": attendees(["Alex S", "Daniel Okafor"]),
        "description": "Prep questions for the vendor verification call with Maya.",
        "location": "WhatsApp call",
        "meet_link": "",
        "recurring": "",
        "attachments": [],
        "calendar_event_id": "",
        "workstream": "Platform",
        "step": "meeting",
    },
    {
        "ref": "m4",
        "key": "M-115",
        "source": "calendar",
        "title": "Ethan Interview Task Handover",
        "date": "2026-09-17",
        "start": "22:30",
        "end": "23:10",
        "organizer": "noah.s@example.com",
        "attendees": attendees(["Aiden Murphy", "Daniel Okafor", "Noah S"]),
        "description": "Team structure, architecture and the take-home assignment.",
        "location": "",
        "meet_link": "meet.google.com/pls-quad-snc",
        "recurring": "",
        "attachments": [{"title": "Notes by Gemini", "kind": "doc"}],
        "calendar_event_id": "ethan17sep",
        "workstream": "Hiring",
        "step": "done",
    },
    {
        "ref": "m5",
        "key": "M-114",
        "source": "calendar",
        "title": "Billing and payments workflows",
        "date": "2026-09-15",
        "start": "15:00",
        "end": "16:00",
        "organizer": "alex.s@example.com",
        "attendees": attendees(["Alex S", "Daniela Mehta", "Daniel Okafor", "Noah S"]),
        "description": "Billing, locale, invites, edit histories.",
        "location": "",
        "meet_link": "meet.google.com/bil-flow-rev",
        "recurring": "",
        "attachments": [{"title": "Notes by Gemini", "kind": "doc"}],
        "calendar_event_id": "bil15sep",
        "workstream": "Billing",
        "step": "done",
    },
    {
        "ref": "m6",
        "key": "M-113",
        "source": "calendar",
        "title": "Standards review: telemetry and alerts",
        "date": "2026-09-15",
        "start": "10:30",
        "end": "11:30",
        "organizer": "daniel.okafor@example.com",
        "attendees": attendees(["Daniel Okafor", "Noah S", "Sofia Silva", "Anna Moreno"]),
        "description": "Alert emission standard v1.2, analytics event standard v1.1.",
        "location": "",
        "meet_link": "meet.google.com/std-rev",
        "recurring": "",
        "attachments": [],
        "calendar_event_id": "std15sep",
        "workstream": "Platform",
        "step": "meeting",
    },
]

# Only these become database rows at bootstrap. m1 and m6 stay calendar-only, so the Step 1 list
# has something to merge and de-duplicate.
SEEDED_MEETING_REFS = {"m2", "m3", "m4", "m5"}

GEMINI_CHAT_NOTE = """The Goal
Determine the product roadmap by comparing expense features against competitors and refining AI receipt analysis workflows.

The Discussion
Competitive Landscape Benchmarking: Analyzed gaps against the three leading expense apps.
AI Accuracy Workflows: Debated receipt analysis reliability, agreeing to implement user-verification steps.
Prioritizing Product Roadmap: Decided to focus on accountant dashboard, tax-line parity and searchability, prioritizing user acquisition over immediate perfection of AI accuracy.

The Next Steps
Anna Moreno: Review dataset for currency information
Noah: Run on-device OCR POC on available Android and iPhone devices
Daniel Okafor: Implement confirmation screen for receipt scanning before results appear on the home screen
Daniel Okafor: Investigate reason for missing tax lines in apps
Unassigned: Develop basic accountant dashboard with client invitations, messaging and target setting"""

NOTES: list[dict[str, Any]] = [
    {
        "ref": "n1",
        "meeting_ref": "m2",
        "source": "paste",
        "title": "Gemini chat summary",
        "created_by": "daniel.okafor@example.com",
        "include": True,
        "text": GEMINI_CHAT_NOTE,
    }
]

POINTS: list[dict[str, Any]] = [
    {
        "ref": "p1",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Review dataset for currency information",
        "owner_text": "Anna Moreno",
        "owner_email": "anna.moreno@example.com",
        "due_text": "26 Sep",
        "status": "open",
        "selected": True,
        "evidence": "Anna Moreno: Review dataset for currency information",
    },
    {
        "ref": "p2",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Run on-device OCR POC on Android and iPhone devices",
        "owner_text": "Noah S",
        "owner_email": "noah.s@example.com",
        "due_text": "30 Sep",
        "status": "open",
        "selected": True,
        "evidence": "Noah: Run on-device OCR POC",
    },
    {
        "ref": "p3",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Implement confirmation screen for receipt scanning before results appear on the home screen",
        "owner_text": "Daniel Okafor",
        "owner_email": "daniel.okafor@example.com",
        "due_text": "3 Oct",
        "status": "in_progress",
        "selected": False,
        "evidence": "",
    },
    {
        "ref": "p4",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Investigate why apps omit or hide tax data",
        "owner_text": "Daniel Okafor",
        "owner_email": "daniel.okafor@example.com",
        "due_text": "",
        "status": "open",
        "selected": False,
        "evidence": "",
    },
    {
        "ref": "p5",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Develop basic accountant dashboard: invites, client list, messaging, target setting",
        "owner_text": "",
        "owner_email": None,
        "due_text": "",
        "status": "open",
        "selected": False,
        "evidence": "",
    },
    {
        "ref": "p6",
        "meeting_ref": "m2",
        "kind": "decision",
        "text": "Prioritise user acquisition over perfecting AI receipt accuracy; add a user verification step for scans",
        "owner_text": "",
        "owner_email": None,
        "due_text": "19 Sep",
        "status": "decided",
        "selected": False,
        "evidence": "",
    },
]

# --- sheets ---------------------------------------------------------------------------------------

STATUS_DD = ["open", "in progress", "blocked", "done", "dropped"]
PRIO_DD = ["P0", "P1", "P2", "P3"]
EFFORT_DD = ["XS", "S", "M", "L"]


def pad(rows: list[list[str]], min_width: int = 8) -> list[list[str]]:
    width = max([min_width, *(len(r) for r in rows)])
    return [[*r, *([""] * (width - len(r)))] for r in rows]


P1_ROWS = pad(
    [
        ["P1 Resolve & Log"],
        ["", "Phase goal: all five capture flows ship; receipt scan is ours alone"],
        [],
        ["", "Owner is the assignee, one person (decided 21 Sep)"],
        [],
        [],
        [],
        [],
        ["ID", "Task", "Owner", "Due", "Priority", "Effort", "Status", "Notes"],
        ["T-101", "Photo capture flow", "Anna Moreno", "5 Sep", "P0", "M", "done", "v1.1"],
        ["T-102", "Manual entry flow", "Anna Moreno", "5 Sep", "P0", "S", "done", ""],
        ["T-103", "Card import flow", "Sofia Silva", "12 Sep", "P1", "S", "done", ""],
        [
            "T-104",
            "Receipt scan flow",
            "Daniel Okafor",
            "12 Sep",
            "P1",
            "M",
            "blocked",
            "OCR accuracy unmeasured",
        ],
        [
            "T-105",
            "Northwind vendor verification call with Maya",
            "Alex S",
            "",
            "P2",
            "XS",
            "open",
            "from 15 Sep sync",
        ],
        [
            "T-106",
            "Mirror OpenRates before launch",
            "Daniel Okafor",
            "3 Oct",
            "P0",
            "S",
            "open",
            "503s past ~10 req/min",
        ],
        [
            "T-107",
            "Confirmation screen for receipt scanning",
            "Daniel Okafor",
            "3 Oct",
            "P1",
            "M",
            "in progress",
            "",
        ],
        [],
        ["", "", "", "", "", "", "", "check dropdown on Status"],
        [],
        [],
    ]
)

P4_ROWS = pad(
    [
        ["P4 Regional & AI"],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        ["ID", "Task", "Owner", "Due", "Priority", "Effort", "Status", "Notes"],
        [
            "T-201",
            "v2.0 multi-currency, VAT, mileage rollup",
            "Anna Moreno",
            "6 Oct",
            "P0",
            "L",
            "in progress",
            "",
        ],
        [
            "T-214",
            "Legal review of tax table",
            "product",
            "3 Oct",
            "P0",
            "XS",
            "blocked",
            "buy an hour of accountant time",
        ],
        [
            "T-215",
            "Parse the vendor CSV exports",
            "Daniel Okafor",
            "10 Oct",
            "P1",
            "S",
            "open",
            "closes most of the 4 vs 84 gap",
        ],
        [],
        [],
    ]
)

DECISIONS_ROWS = pad(
    [
        ["ID", "Decision", "Workstream", "Meeting", "Date", "Status", "Notes"],
        [
            "D-039",
            "Owner column holds a person, not a team",
            "Mobile",
            "Sheet review",
            "21 Sep",
            "decided",
            "",
        ],
        [
            "D-040",
            "Prioritise user acquisition over perfecting AI receipt accuracy; add a verification step",
            "Mobile",
            "Mobile roadmap review",
            "19 Sep",
            "decided",
            "",
        ],
        [
            "Q-011",
            "Is a tip an expense?",
            "Mobile",
            "Mobile roadmap review",
            "19 Sep",
            "open",
            "unblocks two items",
        ],
        [
            "Q-012",
            "Accountant identity model",
            "Mobile",
            "Mobile roadmap review",
            "19 Sep",
            "open",
            "sets the P6 timeline",
        ],
        [],
    ]
)

RISKS_ROWS = pad(
    [
        ["ID", "Risk", "Severity", "Owner", "Mitigation", "Status"],
        [
            "KN-04",
            "Receipt OCR accuracy is unmeasured; totals are where the error lives",
            "High",
            "Daniel Okafor",
            "Verification screen; on-device OCR POC",
            "mitigating",
        ],
        [
            "KN-06",
            "OpenRates 503s past ~10 req/min; must be mirrored before launch",
            "High",
            "Daniel Okafor",
            "Mirror job",
            "open",
        ],
        [
            "KN-09",
            "Card-network licensing cannot be engineered around",
            "High",
            "product",
            "Escalate licensing",
            "open",
        ],
        [],
    ]
)

HW_ROWS = pad(
    [
        ["ID", "Task", "Owner", "Due", "Priority", "Status", "Notes"],
        [
            "H-001",
            "Technical complexity evaluation",
            "Daniela Mehta",
            "17 Sep",
            "P0",
            "in progress",
            "both billing branches costed",
        ],
        [
            "H-002",
            "Billing model decision",
            "Alex S",
            "15 Sep",
            "P0",
            "blocked",
            "single payer vs per-member",
        ],
        [
            "H-010",
            "account, account_member, invite token",
            "Daniela Mehta",
            "10 Oct",
            "P1",
            "open",
            "",
        ],
        [],
    ]
)

SIA_ROWS = pad(
    [
        ["Task", "Points", "Cap", "Status", "Notes"],
        ["Upload an ID", "100", "one time", "live", ""],
        ["Sharing a document", "50", "daily", "live", ""],
        ["Complete profile", "200", "one time", "live", ""],
        [],
    ]
)

WORKBOOKS: list[dict[str, Any]] = [
    {
        "ref": "w1",
        "spreadsheet_id": "1DemoMobileAppRoadmapSpreadsheet000000000001",
        "name": "Mobile App Product Roadmap",
        "url": "https://docs.google.com/spreadsheets/d/1DemoMobileAppRoadmapSpreadsheet000000000001",
        "connected_by": "daniel.okafor@example.com",
        "editors": ["daniel.okafor@example.com"],
        "readers": ["daniel.okafor@example.com", "alex.s@example.com"],
        "tabs": [
            {
                "sheet_id": "t1",
                "title": "P1 Resolve & Log",
                "rows": P1_ROWS,
                "dropdowns": {4: PRIO_DD, 5: EFFORT_DD, 6: STATUS_DD},
            },
            {
                "sheet_id": "t2",
                "title": "P4 Regional & AI",
                "rows": P4_ROWS,
                "dropdowns": {4: PRIO_DD, 5: EFFORT_DD, 6: STATUS_DD},
            },
            {
                "sheet_id": "t3",
                "title": "Decisions",
                "rows": DECISIONS_ROWS,
                "dropdowns": {5: ["decided", "open", "superseded"]},
            },
            {
                "sheet_id": "t4",
                "title": "Risks",
                "rows": RISKS_ROWS,
                "dropdowns": {2: ["High", "Medium", "Low"], 5: ["open", "mitigating", "accepted", "closed"]},
            },
        ],
    },
    {
        "ref": "w2",
        "spreadsheet_id": "1DemoBillingRoadmapSpreadsheet00000000000002",
        "name": "Billing and Payments Roadmap",
        "url": "https://docs.google.com/spreadsheets/d/1DemoBillingRoadmapSpreadsheet00000000000002",
        "connected_by": "daniel.okafor@example.com",
        "editors": ["daniel.okafor@example.com", "alex.s@example.com"],
        "readers": ["daniel.okafor@example.com", "alex.s@example.com"],
        "tabs": [
            {
                "sheet_id": "t5",
                "title": "P0 Evaluation",
                "rows": HW_ROWS,
                "dropdowns": {4: PRIO_DD, 5: STATUS_DD},
            }
        ],
    },
    {
        "ref": "w3",
        "spreadsheet_id": "rewards",
        "name": "Rewards - Earn Points",
        "url": "https://docs.google.com/spreadsheets/d/rewards",
        "connected_by": "alex.s@example.com",
        # Only the second admin connection can edit this one: the connect flow must find it.
        "editors": ["alex.s@example.com"],
        "readers": ["daniel.okafor@example.com", "alex.s@example.com"],
        "tabs": [
            {
                "sheet_id": "t6",
                "title": "Earn Points",
                "rows": SIA_ROWS,
                "dropdowns": {3: ["live", "planned", "removed"]},
            }
        ],
    },
]

# Connected on demand by the tests and the local walkthrough, not seeded.
UNCONNECTED_WORKBOOKS: list[dict[str, Any]] = [
    {
        "spreadsheet_id": "boardmetrics",
        "name": "Board metrics (view only)",
        "url": "https://docs.google.com/spreadsheets/d/boardmetrics",
        "editors": [],
        "readers": ["daniel.okafor@example.com", "alex.s@example.com"],
        "tabs": [
            {
                "sheet_id": "b1",
                "title": "Q3",
                "rows": pad(
                    [
                        ["ID", "Task", "Owner", "Due", "Status"],
                        ["B-001", "Board pack", "Alex S", "1 Oct", "open"],
                        [],
                    ],
                    5,
                ),
                "dropdowns": {},
            }
        ],
    },
]

ACTIVITY: list[dict[str, str]] = [
    {"actor": "daniel.okafor@example.com", "text": "Read P1 Resolve & Log (live)"},
    {"actor": "daniel.okafor@example.com", "text": "Saved note N-302 on Platform squad sync"},
    {"actor": "alex.s@example.com", "text": "Set T-105 Status to open on P1 Resolve & Log"},
    {"actor": "daniel.okafor@example.com", "text": "Connected workbook Rewards - Earn Points"},
]

# --- Notes by Gemini docs -------------------------------------------------------------------------

QUICK_NOTES = """Platform squad sync - quick notes
Upload unification is close; telemetry rollout waits on the alert standard.
Payments spike needs a decision on the vendor."""

FULL_NOTES = """Platform squad sync - full notes

The Goal
Unblock the upload unification work and agree the telemetry rollout order.

The Discussion
Upload unification: the shared uploader is behind a flag on staging.
Telemetry: the alert emission standard v1.2 lands first, then the rollout.
Payments: the vendor spike is unfunded.

The Next Steps
Daniel Okafor: Mirror OpenRates before launch by 3 Oct
Noah: Finish the alert emission standard v1.2 by end of week
Alex S: Northwind vendor verification call with Maya
Decided: the Owner column holds a person, not a team
Open question: do we fund the payments spike this quarter?
Risk: the upload flag has no rollback plan"""

TRANSCRIPT = """00:00 Alex S: Let's start with uploads.
00:14 Daniel Okafor: The shared uploader is behind a flag on staging.
01:02 Noah S: I'll finish the alert standard by end of week.
02:20 Alex S: Decided, the Owner column holds a person, not a team."""

RECAP_EMAIL = """Recap: Platform squad sync

Summary
Upload unification is behind a flag; telemetry waits on the alert standard.

Next steps
Daniel Okafor: Mirror OpenRates before launch by 3 Oct
Noah: Finish the alert emission standard v1.2 by end of week"""

GEMINI_DOCS: list[dict[str, Any]] = [
    {
        "file_id": "doc-m1",
        "meeting_ref": "m1",
        "name": "Platform squad sync - Notes by Gemini",
        "readers": ["daniel.okafor@example.com", "alex.s@example.com"],
        "tabs": [
            {"id": "tab-quick", "title": "Quick notes", "text": QUICK_NOTES},
            {"id": "tab-full", "title": "Full notes", "text": FULL_NOTES},
            {"id": "tab-transcript", "title": "Transcript", "text": TRANSCRIPT},
        ],
    },
    {
        "file_id": "doc-m4",
        "meeting_ref": "m4",
        "name": "Ethan Interview Task Handover - Notes by Gemini",
        # Shared with the second admin only: the reader must fall back across connections.
        "readers": ["alex.s@example.com"],
        "tabs": [
            {
                "id": "tab-quick",
                "title": "Quick notes",
                "text": "Handover: architecture walkthrough and the take-home.",
            },
            {
                "id": "tab-full",
                "title": "Full notes",
                "text": "The Next Steps\nNoah S: Send take-home assignment email to Ethan by Friday\nAiden Murphy: Review the submission",
            },
        ],
    },
    {
        "file_id": "doc-m5",
        "meeting_ref": "m5",
        "name": "Billing and payments workflows - Notes by Gemini",
        "readers": [],  # shared with nobody: the source line says so and paste is right there
        "tabs": [{"id": "tab-full", "title": "Full notes", "text": "Billing model still open."}],
    },
]

RECAP_EMAILS: list[dict[str, Any]] = [
    {
        "id": "msg-m1",
        "meeting_ref": "m1",
        "mailbox": "daniel.okafor@example.com",
        "subject": "Recap: Platform squad sync",
        "from_email": "meet-recap@google.com",
        "body": RECAP_EMAIL,
    }
]


def attachments_for(m: dict[str, Any]) -> list[dict[str, str]]:
    """Calendar attachments carry the Drive file id for a Notes by Gemini doc."""
    return [
        {
            "title": a["title"],
            "kind": a["kind"],
            "file_id": f"doc-{m['ref']}" if a["kind"] == "doc" else "",
            "url": "",
        }
        for a in m["attachments"]
    ]


def meeting_start(m: dict[str, Any]) -> datetime:
    return at(m["date"], m["start"])


def meeting_end(m: dict[str, Any]) -> datetime:
    return at(m["date"], m["end"])


def ical_uid(m: dict[str, Any]) -> str:
    return f"{m['calendar_event_id']}@google.com" if m["calendar_event_id"] else ""


def now() -> datetime:
    """The demo world's "now": just after the last seeded meeting."""
    return at("2026-09-22", "17:02")


def default_window() -> tuple[datetime, datetime]:
    end = now() + timedelta(hours=8)
    return end - timedelta(days=8), end
