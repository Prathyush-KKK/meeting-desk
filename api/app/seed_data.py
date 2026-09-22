"""The prototype's seed, lifted from ``meeting-desk/src/store.tsx``.

It is the single source of demo data: the fake Google builds its calendar, Drive, Docs, Gmail and
Sheets from it, and ``app/bootstrap.py`` writes the same rows into the database so a local run and
the tests see one consistent world.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

PEOPLE: list[dict[str, str]] = [
    {"name": "Ansul S", "email": "ansul.s@simpleo.ai"},
    {"name": "Prathyush Kodhanpur", "email": "prathyush.kodhanpur@simpleo.ai"},
    {"name": "Pratyush Chaudhary", "email": "pratyush.chaudhary@simpleo.ai"},
    {"name": "Nishchay S", "email": "nishchay.s@simpleo.ai"},
    {"name": "Anushka Mohanty", "email": "anushka.mohanty@simpleo.ai"},
    {"name": "Shambhavi Singh", "email": "shambhavi.singh@simpleo.ai"},
    {"name": "Ayush Mishra", "email": "ayush.mishra@simpleo.ai"},
]

# Two people whose first names collide - the spec's ambiguity case.
DIRECTORY: list[dict[str, str]] = [
    *PEOPLE,
    {"name": "Madhu Rao", "email": "madhu.rao@sprinto.com"},
    {"name": "Eshan Verma", "email": "eshan.verma@example.com"},
]

ALIASES: dict[str, str] = {
    "pk": "prathyush.kodhanpur@simpleo.ai",
    "ansul": "ansul.s@simpleo.ai",
    "shambhavi": "shambhavi.singh@simpleo.ai",
}

WORKSTREAMS = ["Nutrition", "Platform", "Household & CDP", "SIApoints", "Prod ops", "Hiring"]

DEMO_USER = "prathyush.kodhanpur@simpleo.ai"

CONNECTIONS: list[dict[str, Any]] = [
    {
        "email": "prathyush.kodhanpur@simpleo.ai",
        "name": "Prathyush Kodhanpur",
        "scopes": [
            "calendar.readonly",
            "drive.readonly",
            "documents.readonly",
            "gmail.readonly",
            "spreadsheets",
        ],
        "connected_at": "2026-09-21T14:02:00+05:30",
        "status": "ok",
    },
    {
        "email": "ansul.s@simpleo.ai",
        "name": "Ansul S",
        "scopes": ["calendar.readonly", "drive.readonly", "spreadsheets"],
        "connected_at": "2026-09-21T18:30:00+05:30",
        "status": "ok",
    },
]

ALLOW_LIST: list[dict[str, str]] = [
    {"email": "prathyush.kodhanpur@simpleo.ai", "role": "admin", "added_by": "setup"},
    {"email": "ansul.s@simpleo.ai", "role": "admin", "added_by": "prathyush.kodhanpur@simpleo.ai"},
    {"email": "nishchay.s@simpleo.ai", "role": "member", "added_by": "prathyush.kodhanpur@simpleo.ai"},
    {
        "email": "pratyush.chaudhary@simpleo.ai",
        "role": "member",
        "added_by": "prathyush.kodhanpur@simpleo.ai",
    },
    {"email": "anushka.mohanty@simpleo.ai", "role": "member", "added_by": "ansul.s@simpleo.ai"},
]


def person(name_or_email: str) -> dict[str, str]:
    for p in PEOPLE:
        if name_or_email in (p["name"], p["email"]):
            return p
    return {"name": name_or_email, "email": name_or_email.lower().replace(" ", ".") + "@simpleo.ai"}


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
    return datetime.combine(date(y, m, d), time(h, mi), tzinfo=IST)


MEETINGS: list[dict[str, Any]] = [
    {
        "ref": "m1",
        "key": "M-118",
        "source": "calendar",
        "title": "Platform squad sync",
        "date": "2026-09-22",
        "start": "16:00",
        "end": "16:48",
        "organizer": "ansul.s@simpleo.ai",
        "attendees": attendees(
            ["Ansul S", "Prathyush Kodhanpur", "Pratyush Chaudhary", "Nishchay S"],
            ["accepted", "accepted", "accepted", "tentative"],
        ),
        "description": "Weekly platform squad sync: upload unification, telemetry, payments, compliance.",
        "location": "",
        "meet_link": "meet.google.com/dzc-eugq-cnt",
        "recurring": "Weekly on Tuesday",
        "attachments": [
            {"title": "Notes by Gemini", "kind": "doc"},
            {"title": "Transcript", "kind": "transcript"},
        ],
        "calendar_event_id": "7jt039pupf1l0iu9b995v8pjj8",
        "workstream": "Platform",
        "step": "meeting",
    },
    {
        "ref": "m2",
        "key": "M-117",
        "source": "calendar",
        "title": "Nutrition roadmap review",
        "date": "2026-09-19",
        "start": "11:00",
        "end": "12:10",
        "organizer": "prathyush.kodhanpur@simpleo.ai",
        "attendees": attendees(
            ["Prathyush Kodhanpur", "Anushka Mohanty", "Nishchay S", "Shambhavi Singh", "Ansul S"]
        ),
        "description": "Compare nutrition features against competitors; refine AI photo analysis workflows.",
        "location": "",
        "meet_link": "meet.google.com/abc-nutr-rev",
        "recurring": "",
        "attachments": [],
        "calendar_event_id": "nutr19sep",
        "workstream": "Nutrition",
        "step": "points",
    },
    {
        "ref": "m3",
        "key": "M-116",
        "source": "manual",
        "title": "Sprinto call prep",
        "date": "2026-09-18",
        "start": "15:00",
        "end": "15:30",
        "organizer": "ansul.s@simpleo.ai",
        "attendees": attendees(["Ansul S", "Prathyush Kodhanpur"]),
        "description": "Prep questions for the vendor verification call with Madhu.",
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
        "title": "Eshan Interview Task Handover",
        "date": "2026-09-17",
        "start": "22:30",
        "end": "23:10",
        "organizer": "nishchay.s@simpleo.ai",
        "attendees": attendees(["Ayush Mishra", "Prathyush Kodhanpur", "Nishchay S"]),
        "description": "Team structure, architecture and the take-home assignment.",
        "location": "",
        "meet_link": "meet.google.com/dzc-eugq-cnt",
        "recurring": "",
        "attachments": [{"title": "Notes by Gemini", "kind": "doc"}],
        "calendar_event_id": "eshan17sep",
        "workstream": "Hiring",
        "step": "done",
    },
    {
        "ref": "m5",
        "key": "M-114",
        "source": "calendar",
        "title": "Household and wealth workflows",
        "date": "2026-09-15",
        "start": "15:00",
        "end": "16:00",
        "organizer": "ansul.s@simpleo.ai",
        "attendees": attendees(["Ansul S", "Pratyush Chaudhary", "Prathyush Kodhanpur", "Nishchay S"]),
        "description": "Billing, locale, invites, edit histories.",
        "location": "",
        "meet_link": "meet.google.com/hh-wealth",
        "recurring": "",
        "attachments": [{"title": "Notes by Gemini", "kind": "doc"}],
        "calendar_event_id": "hw15sep",
        "workstream": "Household & CDP",
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
        "organizer": "prathyush.kodhanpur@simpleo.ai",
        "attendees": attendees(["Prathyush Kodhanpur", "Nishchay S", "Shambhavi Singh", "Anushka Mohanty"]),
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
Determine the product roadmap by comparing nutrition features against competitors and refining AI photo analysis workflows.

The Discussion
Competitive Landscape Benchmarking: Analyzed gaps against apps like Cal AI and MyFitnessPal.
AI Accuracy Workflows: Debated photo analysis reliability, agreeing to implement user-verification steps.
Prioritizing Product Roadmap: Decided to focus on nutritionist dashboard, micronutrient parity and searchability, prioritizing user acquisition over immediate perfection of AI accuracy.

The Next Steps
Anushka Mohanty: Review dataset for weight information
Nishchay: Run depth estimation POC on available Android and iPhone devices
Prathyush Kodhanpur: Implement confirmation screen for food scanning before results appear on the home screen
Prathyush Kodhanpur: Investigate reason for missing micronutrients in apps
Unassigned: Develop basic nutritionist dashboard with client invitations, messaging and target setting"""

NOTES: list[dict[str, Any]] = [
    {
        "ref": "n1",
        "meeting_ref": "m2",
        "source": "paste",
        "title": "Gemini chat summary",
        "created_by": "prathyush.kodhanpur@simpleo.ai",
        "include": True,
        "text": GEMINI_CHAT_NOTE,
    }
]

POINTS: list[dict[str, Any]] = [
    {
        "ref": "p1",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Review dataset for weight information",
        "owner_text": "Anushka Mohanty",
        "owner_email": "anushka.mohanty@simpleo.ai",
        "due_text": "26 Sep",
        "status": "open",
        "selected": True,
        "evidence": "Anushka Mohanty: Review dataset for weight information",
    },
    {
        "ref": "p2",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Run depth estimation POC on Android and iPhone devices",
        "owner_text": "Nishchay S",
        "owner_email": "nishchay.s@simpleo.ai",
        "due_text": "30 Sep",
        "status": "open",
        "selected": True,
        "evidence": "Nishchay: Run depth estimation POC",
    },
    {
        "ref": "p3",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Implement confirmation screen for food scanning before results appear on the home screen",
        "owner_text": "Prathyush Kodhanpur",
        "owner_email": "prathyush.kodhanpur@simpleo.ai",
        "due_text": "3 Oct",
        "status": "in_progress",
        "selected": False,
        "evidence": "",
    },
    {
        "ref": "p4",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Investigate why apps omit or hide micronutrient data",
        "owner_text": "Prathyush Kodhanpur",
        "owner_email": "prathyush.kodhanpur@simpleo.ai",
        "due_text": "",
        "status": "open",
        "selected": False,
        "evidence": "",
    },
    {
        "ref": "p5",
        "meeting_ref": "m2",
        "kind": "action",
        "text": "Develop basic nutritionist dashboard: invites, client list, messaging, target setting",
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
        "text": "Prioritise user acquisition over perfecting AI photo accuracy; add a user verification step for scans",
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
        ["", "Phase goal: all five logging paths ship; menu scan is ours alone"],
        [],
        ["", "Owner is the assignee, one person (decided 21 Sep)"],
        [],
        [],
        [],
        [],
        ["ID", "Task", "Owner", "Due", "Priority", "Effort", "Status", "Notes"],
        ["T-101", "Photo logging path", "Anushka Mohanty", "5 Sep", "P0", "M", "done", "v1.1"],
        ["T-102", "Search logging path", "Anushka Mohanty", "5 Sep", "P0", "S", "done", ""],
        ["T-103", "Barcode logging path", "Shambhavi Singh", "12 Sep", "P1", "S", "done", ""],
        [
            "T-104",
            "Menu scan logging path",
            "Prathyush Kodhanpur",
            "12 Sep",
            "P1",
            "M",
            "blocked",
            "portion accuracy unmeasured",
        ],
        [
            "T-105",
            "Sprinto vendor verification call with Madhu",
            "Ansul S",
            "",
            "P2",
            "XS",
            "open",
            "from 15 Sep sync",
        ],
        [
            "T-106",
            "Mirror Open Food Facts before launch",
            "Prathyush Kodhanpur",
            "3 Oct",
            "P0",
            "S",
            "open",
            "503s past ~10 req/min",
        ],
        [
            "T-107",
            "Confirmation screen for food scanning",
            "Prathyush Kodhanpur",
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
            "v2.0 micronutrients, supplements, fibre rollup",
            "Anushka Mohanty",
            "6 Oct",
            "P0",
            "L",
            "in progress",
            "",
        ],
        [
            "T-214",
            "Clinical review of RDA table",
            "product",
            "3 Oct",
            "P0",
            "XS",
            "blocked",
            "buy an hour of clinician time",
        ],
        [
            "T-215",
            "Parse CoFID vitamin sheets",
            "Prathyush Kodhanpur",
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
            "Nutrition",
            "Sheet review",
            "21 Sep",
            "decided",
            "",
        ],
        [
            "D-040",
            "Prioritise user acquisition over perfecting AI photo accuracy; add a verification step",
            "Nutrition",
            "Nutrition roadmap review",
            "19 Sep",
            "decided",
            "",
        ],
        [
            "Q-011",
            "Is a drink a meal?",
            "Nutrition",
            "Nutrition roadmap review",
            "19 Sep",
            "open",
            "unblocks two items",
        ],
        [
            "Q-012",
            "Practitioner identity model",
            "Nutrition",
            "Nutrition roadmap review",
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
            "Photo portion accuracy is unmeasured; portion is where the error lives",
            "High",
            "Prathyush Kodhanpur",
            "Verification screen; depth estimation POC",
            "mitigating",
        ],
        [
            "KN-06",
            "Open Food Facts 503s past ~10 req/min; must be mirrored before launch",
            "High",
            "Prathyush Kodhanpur",
            "Mirror job",
            "open",
        ],
        [
            "KN-09",
            "IFCT licensing cannot be engineered around",
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
            "Pratyush Chaudhary",
            "17 Sep",
            "P0",
            "in progress",
            "both billing branches costed",
        ],
        [
            "H-002",
            "Billing model decision",
            "Ansul S",
            "15 Sep",
            "P0",
            "blocked",
            "single payer vs per-member",
        ],
        [
            "H-010",
            "household, household_member, invite token",
            "Pratyush Chaudhary",
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
        "spreadsheet_id": "1TXxibAPO60bB4e1GUQumZKBW68ATv0MrpIinlCwDL8Q",
        "name": "Nutrition Sialet Product Roadmap",
        "url": "https://docs.google.com/spreadsheets/d/1TXxibAPO60bB4e1GUQumZKBW68ATv0MrpIinlCwDL8Q",
        "connected_by": "prathyush.kodhanpur@simpleo.ai",
        "editors": ["prathyush.kodhanpur@simpleo.ai"],
        "readers": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
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
        "spreadsheet_id": "1MiVEOVKWwJyMOySoHIhv0leStcdenRoJE0KrULeLQcU",
        "name": "Household Wealth and CDP Roadmap",
        "url": "https://docs.google.com/spreadsheets/d/1MiVEOVKWwJyMOySoHIhv0leStcdenRoJE0KrULeLQcU",
        "connected_by": "prathyush.kodhanpur@simpleo.ai",
        "editors": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
        "readers": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
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
        "spreadsheet_id": "siapoints",
        "name": "SIApoints - Earn Points",
        "url": "https://docs.google.com/spreadsheets/d/siapoints",
        "connected_by": "ansul.s@simpleo.ai",
        # Only the second admin connection can edit this one: the connect flow must find it.
        "editors": ["ansul.s@simpleo.ai"],
        "readers": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
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
        "readers": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
        "tabs": [
            {
                "sheet_id": "b1",
                "title": "Q3",
                "rows": pad(
                    [
                        ["ID", "Task", "Owner", "Due", "Status"],
                        ["B-001", "Board pack", "Ansul S", "1 Oct", "open"],
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
    {"actor": "prathyush.kodhanpur@simpleo.ai", "text": "Read P1 Resolve & Log (live)"},
    {"actor": "prathyush.kodhanpur@simpleo.ai", "text": "Saved note N-302 on Platform squad sync"},
    {"actor": "ansul.s@simpleo.ai", "text": "Set T-105 Status to open on P1 Resolve & Log"},
    {"actor": "prathyush.kodhanpur@simpleo.ai", "text": "Connected workbook SIApoints - Earn Points"},
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
Prathyush Kodhanpur: Mirror Open Food Facts before launch by 3 Oct
Nishchay: Finish the alert emission standard v1.2 by end of week
Ansul S: Sprinto vendor verification call with Madhu
Decided: the Owner column holds a person, not a team
Open question: do we fund the payments spike this quarter?
Risk: the upload flag has no rollback plan"""

TRANSCRIPT = """00:00 Ansul S: Let's start with uploads.
00:14 Prathyush Kodhanpur: The shared uploader is behind a flag on staging.
01:02 Nishchay S: I'll finish the alert standard by end of week.
02:20 Ansul S: Decided, the Owner column holds a person, not a team."""

RECAP_EMAIL = """Recap: Platform squad sync

Summary
Upload unification is behind a flag; telemetry waits on the alert standard.

Next steps
Prathyush Kodhanpur: Mirror Open Food Facts before launch by 3 Oct
Nishchay: Finish the alert emission standard v1.2 by end of week"""

GEMINI_DOCS: list[dict[str, Any]] = [
    {
        "file_id": "doc-m1",
        "meeting_ref": "m1",
        "name": "Platform squad sync - Notes by Gemini",
        "readers": ["prathyush.kodhanpur@simpleo.ai", "ansul.s@simpleo.ai"],
        "tabs": [
            {"id": "tab-quick", "title": "Quick notes", "text": QUICK_NOTES},
            {"id": "tab-full", "title": "Full notes", "text": FULL_NOTES},
            {"id": "tab-transcript", "title": "Transcript", "text": TRANSCRIPT},
        ],
    },
    {
        "file_id": "doc-m4",
        "meeting_ref": "m4",
        "name": "Eshan Interview Task Handover - Notes by Gemini",
        # Shared with the second admin only: the reader must fall back across connections.
        "readers": ["ansul.s@simpleo.ai"],
        "tabs": [
            {
                "id": "tab-quick",
                "title": "Quick notes",
                "text": "Handover: architecture walkthrough and the take-home.",
            },
            {
                "id": "tab-full",
                "title": "Full notes",
                "text": "The Next Steps\nNishchay S: Send take-home assignment email to Eshan by Friday\nAyush Mishra: Review the submission",
            },
        ],
    },
    {
        "file_id": "doc-m5",
        "meeting_ref": "m5",
        "name": "Household and wealth workflows - Notes by Gemini",
        "readers": [],  # shared with nobody: the source line says so and paste is right there
        "tabs": [{"id": "tab-full", "title": "Full notes", "text": "Billing model still open."}],
    },
]

RECAP_EMAILS: list[dict[str, Any]] = [
    {
        "id": "msg-m1",
        "meeting_ref": "m1",
        "mailbox": "prathyush.kodhanpur@simpleo.ai",
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
