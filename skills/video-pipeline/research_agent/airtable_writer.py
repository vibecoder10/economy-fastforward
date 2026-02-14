"""Airtable Writer for Research Intelligence Agent.

Manages the Ideas Bank table with exact field names matching the Airtable schema.
Uses direct REST API calls for precise control over field names.
"""

import os
import json
import requests
from datetime import date
from typing import Optional


class ResearchAirtableWriter:
    """Airtable client for Research Intelligence Agent Ideas Bank table."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_id: Optional[str] = None,
    ):
        """Initialize the Airtable writer.

        Args:
            api_key: Airtable Personal Access Token (or from AIRTABLE_PAT env var)
            base_id: Airtable base ID (or from AIRTABLE_BASE_ID env var)
        """
        self.api_key = api_key or os.getenv("AIRTABLE_PAT") or os.getenv("AIRTABLE_API_KEY")
        if not self.api_key:
            raise ValueError("AIRTABLE_PAT or AIRTABLE_API_KEY not found in environment")

        self.base_id = base_id or os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
        self.table_name = "Ideas%20Bank"
        self.base_url = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        payload: Optional[dict] = None,
        params: Optional[dict] = None,
        max_retries: int = 3,
    ) -> dict:
        """Make an Airtable API request with retry logic.

        Args:
            method: HTTP method (GET, POST, PATCH)
            payload: JSON payload for POST/PATCH
            params: Query parameters for GET
            max_retries: Number of retries on failure

        Returns:
            Response JSON dict
        """
        import time

        for attempt in range(max_retries):
            try:
                if method == "GET":
                    response = requests.get(
                        self.base_url,
                        headers=self.headers,
                        params=params,
                        timeout=30,
                    )
                elif method == "POST":
                    response = requests.post(
                        self.base_url,
                        headers=self.headers,
                        json=payload,
                        timeout=30,
                    )
                elif method == "PATCH":
                    response = requests.patch(
                        self.base_url,
                        headers=self.headers,
                        json=payload,
                        timeout=30,
                    )
                else:
                    raise ValueError(f"Unsupported method: {method}")

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 422:
                    # Validation error - bad field name or value
                    error_data = response.json()
                    raise ValueError(f"Airtable validation error: {error_data}")
                elif response.status_code == 429:
                    # Rate limited
                    wait = int(response.headers.get("Retry-After", 30))
                    print(f"    Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                elif response.status_code == 404:
                    raise ValueError(
                        f"Table not found. Make sure 'Ideas Bank' table exists in base {self.base_id}"
                    )
                else:
                    print(f"    Airtable error {response.status_code}: {response.text}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    raise ValueError(f"Airtable request failed: {response.status_code}")

            except requests.exceptions.RequestException as e:
                print(f"    Network error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                raise

        raise ValueError("Max retries exceeded")

    # ==================== WRITE CANDIDATES ====================

    def write_candidates(self, candidates: list[dict]) -> list[dict]:
        """Write candidate ideas from a broad scan to Airtable.

        Args:
            candidates: List of candidate dicts from the scanner

        Returns:
            List of created record dicts with IDs
        """
        records = []
        for c in candidates:
            # Map scanner output to exact Airtable field names
            fields = {
                "Headline": c.get("headline", "")[:100000],
                "Source Category": c.get("source_category", "breaking_news"),
                "Timeliness Score": int(c.get("timeliness_score", 5)),
                "Audience Fit Score": int(c.get("audience_fit_score", 5)),
                "Content Gap Score": int(c.get("content_gap_score", 5)),
                "Framework Angle": self._map_framework(c.get("framework_hint", "")),
                "Source URLs": "\n".join(c.get("source_urls", [])),
                "Status": "candidate",
                "Date Surfaced": date.today().isoformat(),
                "Evergreen Flag": c.get("evergreen", False),
                "Monetization Risk": self._map_monetization_risk(c.get("kill_flags", [])),
            }

            # Optional fields
            if c.get("competitor_coverage"):
                fields["Competitor Coverage"] = c["competitor_coverage"]
            if c.get("reasoning"):
                fields["Notes"] = c["reasoning"]

            records.append({"fields": fields})

        # Batch write (max 10 per request)
        created_records = []
        for i in range(0, len(records), 10):
            batch = records[i:i + 10]
            payload = {"records": batch, "typecast": True}  # Auto-create select options

            try:
                result = self._make_request("POST", payload=payload)
                for rec in result.get("records", []):
                    created_records.append({
                        "id": rec["id"],
                        "headline": rec["fields"].get("Headline", ""),
                    })
                    print(f"    Created: {rec['id']} — {rec['fields'].get('Headline', '')[:50]}")
            except Exception as e:
                print(f"    Error creating batch: {e}")

        return created_records

    def _map_framework(self, framework_hint: str) -> str:
        """Map framework hint to Airtable single select option.

        Valid options: Machiavelli, 48 Laws, Jung Shadow, Game Theory,
        Sun Tzu, Behavioral Econ, Stoicism, Systems Thinking, Propaganda, Evolutionary Psych
        """
        hint_lower = framework_hint.lower()

        mapping = {
            "machiavelli": "Machiavelli",
            "prince": "Machiavelli",
            "48 law": "48 Laws",
            "law of power": "48 Laws",
            "greene": "48 Laws",
            "jung": "Jung Shadow",
            "shadow": "Jung Shadow",
            "game theory": "Game Theory",
            "nash": "Game Theory",
            "prisoner": "Game Theory",
            "sun tzu": "Sun Tzu",
            "art of war": "Sun Tzu",
            "behavioral": "Behavioral Econ",
            "kahneman": "Behavioral Econ",
            "bias": "Behavioral Econ",
            "stoic": "Stoicism",
            "marcus aurelius": "Stoicism",
            "epictetus": "Stoicism",
            "system": "Systems Thinking",
            "feedback": "Systems Thinking",
            "propaganda": "Propaganda",
            "bernays": "Propaganda",
            "cialdini": "Propaganda",
            "evolution": "Evolutionary Psych",
            "tribal": "Evolutionary Psych",
            "dawkins": "Evolutionary Psych",
        }

        for key, value in mapping.items():
            if key in hint_lower:
                return value

        # Default to most common
        return "48 Laws"

    def _map_monetization_risk(self, kill_flags: list) -> str:
        """Map kill flags to monetization risk level."""
        if not kill_flags:
            return "low"

        flags_str = " ".join(kill_flags).lower()
        if "monetization" in flags_str or "violence" in flags_str or "hate" in flags_str:
            return "high"
        elif "risk" in flags_str or "sensitive" in flags_str:
            return "medium"
        return "low"

    # ==================== UPDATE STATUS ====================

    def mark_selected(self, record_id: str, is_primary: bool = True) -> dict:
        """Mark a candidate as selected for deep dive.

        Args:
            record_id: Airtable record ID
            is_primary: True for primary pick, False for backlog

        Returns:
            Updated record dict
        """
        payload = {
            "records": [
                {
                    "id": record_id,
                    "fields": {
                        "Status": "selected" if is_primary else "backlog"
                    }
                }
            ],
            "typecast": True  # Auto-create select options
        }

        result = self._make_request("PATCH", payload=payload)
        return result.get("records", [{}])[0]

    def mark_backlog(self, record_ids: list[str]) -> list[dict]:
        """Mark multiple candidates as backlog.

        Args:
            record_ids: List of Airtable record IDs

        Returns:
            List of updated records
        """
        records = [
            {"id": rid, "fields": {"Status": "backlog"}}
            for rid in record_ids
        ]

        updated = []
        for i in range(0, len(records), 10):
            batch = records[i:i + 10]
            payload = {"records": batch}
            result = self._make_request("PATCH", payload=payload)
            updated.extend(result.get("records", []))

        return updated

    # ==================== DEEP DIVE UPDATE ====================

    def update_with_deep_dive(self, record_id: str, deep_dive: dict) -> dict:
        """Update a record with deep dive research results.

        Args:
            record_id: Airtable record ID
            deep_dive: Dict containing deep dive outputs

        Returns:
            Updated record dict
        """
        fields = {
            "Status": "researched",
            "Date Deep Dived": date.today().isoformat(),
        }

        # Map deep dive fields to exact Airtable field names
        field_mapping = {
            "executive_hook": "Executive Hook",
            "thesis": "Thesis",
            "fact_sheet": "Fact Sheet",
            "historical_parallels": "Historical Parallels",
            "framework_analysis": "Framework Analysis",
            "character_dossier": "Character Dossier",
            "narrative_arc": "Narrative Arc",
            "counter_arguments": "Counter Arguments",
            "visual_seeds": "Visual Seeds",
            "title_options": "Title Options",
            "thumbnail_concepts": "Thumbnail Concepts",
            "source_bibliography": "Source Bibliography",
        }

        for source_key, airtable_field in field_mapping.items():
            if source_key in deep_dive and deep_dive[source_key]:
                value = deep_dive[source_key]
                # Convert lists/dicts to formatted strings
                if isinstance(value, list):
                    value = "\n".join(str(v) for v in value)
                elif isinstance(value, dict):
                    value = json.dumps(value, indent=2)
                fields[airtable_field] = str(value)[:100000]

        payload = {
            "records": [
                {
                    "id": record_id,
                    "fields": fields
                }
            ],
            "typecast": True  # Auto-create select options
        }

        result = self._make_request("PATCH", payload=payload)
        return result.get("records", [{}])[0]

    # ==================== READ OPERATIONS ====================

    def get_ideas_by_status(self, status: str, max_records: int = 10) -> list[dict]:
        """Fetch ideas filtered by status.

        Args:
            status: Status to filter by (candidate, selected, researched, etc.)
            max_records: Maximum records to return

        Returns:
            List of record dicts
        """
        params = {
            "filterByFormula": f"{{Status}} = '{status}'",
            "maxRecords": max_records,
            "sort[0][field]": "Audience Fit Score",
            "sort[0][direction]": "desc",
        }

        result = self._make_request("GET", params=params)
        return result.get("records", [])

    def get_researched_ideas(self, max_records: int = 5) -> list[dict]:
        """Get researched ideas ready for pipeline graduation.

        Returns:
            List of researched idea records sorted by composite score
        """
        return self.get_ideas_by_status("researched", max_records)

    # ==================== PIPELINE GRADUATION ====================

    def graduate_to_pipeline(
        self,
        idea_record_id: str,
        pipeline_table_name: str = "Ideas",
    ) -> Optional[str]:
        """Create a record in the existing pipeline table from a researched idea.

        Args:
            idea_record_id: Ideas Bank record ID
            pipeline_table_name: Name of the pipeline table (URL-encoded)

        Returns:
            Pipeline record ID if successful, None otherwise
        """
        # First, fetch the idea data
        params = {
            "filterByFormula": f"RECORD_ID() = '{idea_record_id}'",
            "maxRecords": 1,
        }
        result = self._make_request("GET", params=params)
        records = result.get("records", [])

        if not records:
            print(f"    Idea record not found: {idea_record_id}")
            return None

        idea = records[0]["fields"]

        # Create pipeline record
        pipeline_url = f"https://api.airtable.com/v0/{self.base_id}/{pipeline_table_name}"

        # Extract first title option
        title_options = idea.get("Title Options", "")
        first_title = title_options.split("\n")[0] if title_options else idea.get("Headline", "")

        pipeline_fields = {
            "Video Title": first_title,
            "Hook Script": idea.get("Executive Hook", ""),
            "Past Context": idea.get("Historical Parallels", ""),
            "Present Parallel": idea.get("Framework Analysis", ""),
            "Future Prediction": idea.get("Narrative Arc", ""),
            "Writer Guidance": f"Framework: {idea.get('Framework Angle', '')}. Thesis: {idea.get('Thesis', '')}.",
            "Thumbnail Prompt": (idea.get("Thumbnail Concepts", "") or "").split("\n")[0],
            "Status": "Idea Logged",
        }

        # Add source URL if available
        source_urls = idea.get("Source URLs", "")
        if source_urls:
            pipeline_fields["Reference URL"] = source_urls.split("\n")[0]

        payload = {"records": [{"fields": pipeline_fields}]}

        try:
            response = requests.post(
                pipeline_url,
                headers=self.headers,
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                pipeline_record_id = response.json()["records"][0]["id"]
                print(f"    Pipeline record created: {pipeline_record_id}")

                # Update Ideas Bank status
                self._make_request("PATCH", payload={
                    "records": [{
                        "id": idea_record_id,
                        "fields": {"Status": "sent_to_pipeline"}
                    }]
                })

                return pipeline_record_id
            else:
                print(f"    Error creating pipeline record: {response.status_code} — {response.text}")
                return None
        except Exception as e:
            print(f"    Error graduating to pipeline: {e}")
            return None

    # ==================== SCAN RESULTS WRITER ====================

    def write_scan_results(
        self,
        scan_result: dict,
        trigger_type: str = "manual_api",
    ) -> dict:
        """Write complete Phase 1 scan results to Airtable.

        This is the main entry point for writing scan results.

        Args:
            scan_result: Output from ResearchScanner.run_full_phase1()
            trigger_type: For logging (not written to Ideas Bank)

        Returns:
            Dict with created record IDs and picks
        """
        print("\n[AIRTABLE WRITER] Writing scan results to Ideas Bank...")

        candidates = scan_result.get("all_candidates", [])

        # Write all candidates
        created_records = self.write_candidates(candidates)

        # Build record ID map
        id_map = {r["headline"]: r["id"] for r in created_records}

        # Identify picks
        primary_pick_id = None
        secondary_pick_id = None

        for candidate in candidates:
            headline = candidate.get("headline", "")
            rec_id = id_map.get(headline)

            if not rec_id:
                continue

            if candidate.get("selection_recommendation") == "primary":
                primary_pick_id = rec_id
                self.mark_selected(rec_id, is_primary=True)
                print(f"    Marked primary: {headline[:50]}...")
            elif candidate.get("selection_recommendation") == "secondary":
                secondary_pick_id = rec_id
                self.mark_selected(rec_id, is_primary=False)
                print(f"    Marked secondary: {headline[:50]}...")

        print(f"\n  Written {len(created_records)} candidates to Ideas Bank")

        return {
            "idea_record_ids": [r["id"] for r in created_records],
            "primary_pick_id": primary_pick_id,
            "secondary_pick_id": secondary_pick_id,
        }
