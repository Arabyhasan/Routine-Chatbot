"""
sheets_integration.py — Google Sheets weekly schedule view.

Creates and maintains one spreadsheet:
  - Columns: Mon–Sun with real dates (next 7 days from Monday of current week)
  - Rows: 8:00 AM → 10:00 PM in 30-min steps
  - Cells: commitment name OR "Free"
  - Colors: green (free) | orange (reschedulable) | red (fixed/locked)

Auto-updates:
  - Called automatically after every mutation (schedule, reschedule, cancel, add)
  - Rolls to next week every Monday (headers + data rebuilt, same spreadsheet)
  - State (spreadsheet ID + current week) stored in sheet_state.json
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List, Optional

from googleapiclient.discovery import build

from models import Commitment, DayOfWeek, TimeSlot
from routine_manager import load_routine


# ─── Layout constants ─────────────────────────────────────────────────────────

WORK_START     = time(8, 0)
WORK_END       = time(22, 0)
STEP_MINUTES   = 30
SHEET_TITLE    = "Routine Agent — Weekly Schedule"
STATE_FILE     = "sheet_state.json"

# Colors (RGB 0–1 floats for the Sheets API)
C_HEADER_BG   = {"red": 0.17, "green": 0.24, "blue": 0.31}   # dark slate
C_HEADER_FG   = {"red": 1.00, "green": 1.00, "blue": 1.00}   # white
C_TODAY_BG    = {"red": 0.27, "green": 0.51, "blue": 0.71}   # blue highlight
C_TIME_COL    = {"red": 0.93, "green": 0.93, "blue": 0.93}   # light grey
C_FREE        = {"red": 0.85, "green": 0.93, "blue": 0.83}   # light green
C_BUSY        = {"red": 0.99, "green": 0.90, "blue": 0.80}   # light orange
C_LOCKED      = {"red": 0.96, "green": 0.80, "blue": 0.80}   # light red
C_WHITE       = {"red": 1.00, "green": 1.00, "blue": 1.00}


class SheetsIntegration:
    def __init__(self, creds):
        self.creds = creds
        self._sheets = None
        self._drive  = None

    @property
    def sheets(self):
        if self._sheets is None:
            self._sheets = build("sheets", "v4", credentials=self.creds)
        return self._sheets

    @property
    def drive(self):
        if self._drive is None:
            self._drive = build("drive", "v3", credentials=self.creds)
        return self._drive

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, spreadsheet_id: str, week_start: date, url: str):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"spreadsheet_id": spreadsheet_id,
                 "week_start": week_start.isoformat(),
                 "sheet_url": url},
                f, indent=2
            )

    def get_sheet_url(self) -> Optional[str]:
        return self._load_state().get("sheet_url")

    # ── Spreadsheet find / create ─────────────────────────────────────────────

    def _find_existing(self) -> Optional[str]:
        """Return spreadsheet ID if the sheet already exists in Drive."""
        state = self._load_state()
        if state.get("spreadsheet_id"):
            # Verify it still exists
            try:
                self.sheets.spreadsheets().get(
                    spreadsheetId=state["spreadsheet_id"]
                ).execute()
                return state["spreadsheet_id"]
            except Exception:
                pass  # deleted externally — recreate

        try:
            results = self.drive.files().list(
                q=f"name='{SHEET_TITLE}' and "
                  f"mimeType='application/vnd.google-apps.spreadsheet' and "
                  f"trashed=false",
                fields="files(id,name)",
                pageSize=1,
            ).execute()
            files = results.get("files", [])
            if files:
                return files[0]["id"]
        except Exception:
            pass
        return None

    def _create_spreadsheet(self) -> str:
        """Create a fresh spreadsheet and return its ID."""
        ss = self.sheets.spreadsheets().create(body={
            "properties": {"title": SHEET_TITLE},
            "sheets": [{"properties": {"title": "Schedule", "sheetId": 0}}],
        }).execute()
        return ss["spreadsheetId"]

    def _get_or_create(self) -> str:
        sid = self._find_existing()
        if not sid:
            sid = self._create_spreadsheet()
        return sid

    # ── Grid helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _week_start() -> date:
        today = date.today()
        return today - timedelta(days=today.weekday())  # Monday

    @staticmethod
    def _time_slots() -> List[time]:
        slots: List[time] = []
        cursor = datetime.combine(date.today(), WORK_START)
        end    = datetime.combine(date.today(), WORK_END)
        while cursor <= end:
            slots.append(cursor.time())
            cursor += timedelta(minutes=STEP_MINUTES)
        return slots

    @staticmethod
    def _cell_for(slot_start: time, d: date, commitments: List[Commitment]) -> tuple[str, Optional[Commitment]]:
        """Return (cell_text, matching_commitment_or_None) for a slot."""
        day_enum  = DayOfWeek(d.strftime("%A").lower())
        end_dt    = datetime.combine(d, slot_start) + timedelta(minutes=STEP_MINUTES)
        slot      = TimeSlot(start=slot_start, end=end_dt.time())
        for c in commitments:
            if day_enum in c.days and slot.overlaps(c.time_slot):
                return c.title, c
        return "Free", None

    # ── Main sync ─────────────────────────────────────────────────────────────

    def sync(self, routine_path: str = "routine.json") -> str:
        """
        Full sync: rebuild headers, data, and formatting.
        Safe to call after every mutation — only formats cells that changed.
        Returns the sheet URL.
        """
        commitments  = load_routine(routine_path)
        week_start   = self._week_start()
        dates        = [week_start + timedelta(days=i) for i in range(7)]
        time_slots   = self._time_slots()
        today        = date.today()

        sid = self._get_or_create()
        url = f"https://docs.google.com/spreadsheets/d/{sid}"

        # ── 1. Build value grid ───────────────────────────────────────────────
        header = ["Time"] + [d.strftime("%a\n%d %b") for d in dates]
        rows   = [header]
        for s in time_slots:
            row = [s.strftime("%I:%M %p")]
            for d in dates:
                text, _ = self._cell_for(s, d, commitments)
                row.append(text)
            rows.append(row)

        self.sheets.spreadsheets().values().update(
            spreadsheetId=sid,
            range="Schedule!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

        # ── 2. Formatting ─────────────────────────────────────────────────────
        reqs: list = []
        n_rows = len(time_slots)
        n_cols = 8   # A + 7 days

        # Freeze header row and Time column
        reqs.append({"updateSheetProperties": {
            "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }})

        # Header row
        reqs.append({"repeatCell": {
            "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "cell": {"userEnteredFormat": {
                "backgroundColor": C_HEADER_BG,
                "textFormat": {"foregroundColor": C_HEADER_FG, "bold": True, "fontSize": 10},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat",
        }})

        # Today column highlight (override header bg for that column)
        for col_idx, d in enumerate(dates):
            if d == today:
                reqs.append({"repeatCell": {
                    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": col_idx + 1, "endColumnIndex": col_idx + 2},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": C_TODAY_BG,
                        "textFormat": {"foregroundColor": C_HEADER_FG, "bold": True, "fontSize": 10},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }},
                    "fields": "userEnteredFormat",
                }})

        # Time column (A)
        reqs.append({"repeatCell": {
            "range": {"sheetId": 0, "startRowIndex": 1, "endRowIndex": n_rows + 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": C_TIME_COL,
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat",
        }})

        # Data cells
        for row_idx, s in enumerate(time_slots):
            for col_idx, d in enumerate(dates):
                _, commitment = self._cell_for(s, d, commitments)
                if commitment is None:
                    bg = C_FREE
                elif not commitment.reschedulable:
                    bg = C_LOCKED    # red — fixed (class, locked work meeting)
                else:
                    bg = C_BUSY     # orange — moveable (gym, deep work, lunch)

                reqs.append({"repeatCell": {
                    "range": {"sheetId": 0,
                              "startRowIndex": row_idx + 1, "endRowIndex": row_idx + 2,
                              "startColumnIndex": col_idx + 1, "endColumnIndex": col_idx + 2},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": bg,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }},
                    "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment)",
                }})

        # Column widths: A=90px, B-H=130px
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 90}, "fields": "pixelSize",
        }})
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 8},
            "properties": {"pixelSize": 130}, "fields": "pixelSize",
        }})

        # Row heights: header=45px, data=25px
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 45}, "fields": "pixelSize",
        }})
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 1, "endIndex": n_rows + 1},
            "properties": {"pixelSize": 25}, "fields": "pixelSize",
        }})

        # Border around entire table
        reqs.append({"updateBorders": {
            "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": n_rows + 1,
                      "startColumnIndex": 0, "endColumnIndex": n_cols},
            "innerHorizontal": {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
            "innerVertical":   {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
        }})

        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=sid, body={"requests": reqs}
        ).execute()

        self._save_state(sid, week_start, url)
        return url
