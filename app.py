import streamlit as st
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import uuid
import datetime
import random

# ============================================================
# CONFIG
# ============================================================
STORIES_PER_SET = 5          # stories available per system per prompt
NUM_ANNOTATORS = 3
SHARED_COUNT = 25            # prompts every annotator sees (for inter-rater agreement)
UNIQUE_COUNT = 25            # prompts unique to each annotator
ASSIGNMENT_SEED = 99

ASSIGNMENT_FILE = "./prompt_assignments.json"

COMPARISON_DIMENSIONS = [
    {
        "key": "quality",
        "label": "Quality",
        "question": "Which story is higher quality?",
        "description": "Consider writing craft, coherence, fluency, and how well it responds to the prompt.",
    },
]

TIE_OPTION = True   # "Same" is available as a choice
# SHEET_NAME = "creative_writing_baco_pairwise_single_annotations"
SHEET_NAME = "creative_writing_pairwise_annotations"
DATA_FILE  = "./merged_generations.json"

VALID_ANNOTATOR_IDS = [str(i) for i in range(1, NUM_ANNOTATORS + 1)]


# ============================================================
# ASSIGNMENT LOADING
# ============================================================
@st.cache_data
def load_assignment_map():
    """
    Loads prompt assignments from prompt_assignments.json.
    Expected format: {"1": [{"prompt": int, "story_idx_a": int, "story_idx_b": int, "shared": bool}, ...], ...}
    """
    with open(ASSIGNMENT_FILE, "r") as f:
        raw = json.load(f)
    return {str(k): v for k, v in raw.items()}


# ============================================================
# DATA LOADING
# ============================================================
@st.cache_data
def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)


# ============================================================
# GOOGLE SHEETS
# ============================================================
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_sheet():
    gcp_creds = st.secrets["gcp"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(gcp_creds, SCOPE)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).sheet1

# def save_annotations(annotator_id, session_id, all_data):
#     sheet = get_sheet()
#     serializable = {str(k): v for k, v in all_data.items()}
#     json_data = json.dumps(serializable)
#     timestamp = datetime.datetime.now().isoformat()

#     rows = sheet.get_all_values()
#     row_index = None
#     for idx, row in enumerate(rows[1:], start=2):
#         if row[0] == annotator_id and row[1] == session_id:
#             row_index = idx
#             break

#     if row_index:
#         sheet.update(f"A{row_index}:D{row_index}",
#                      [[annotator_id, session_id, json_data, timestamp]])
#     else:
#         sheet.append_row([annotator_id, session_id, json_data, timestamp])
def save_annotations(annotator_id, session_id, all_data):
    sheet = get_sheet()

    # Only save annotation metadata + judgments.
    # Stories/prompts remain in merged_generations.json.
    compact_data = {}

    for page, ann in all_data.items():
        compact_data[str(page)] = {
            "page_index": ann["page_index"],
            "prompt_index": ann["prompt_index"],
            "shared": ann["shared"],
            "story_idx_a": ann["story_idx_a"],
            "story_idx_b": ann["story_idx_b"],
            "display_order": ann["display_order"],
            "system_a_label": ann["system_a_label"],
            "system_b_label": ann["system_b_label"],
            "judgements": ann["judgements"],
            "comments": ann.get("comments", ""),
        }

    json_data = json.dumps(compact_data)
    timestamp = datetime.datetime.now().isoformat()

    rows = sheet.get_all_values()
    row_index = None

    for idx, row in enumerate(rows[1:], start=2):
        if row[0] == annotator_id and row[1] == session_id:
            row_index = idx
            break

    if row_index:
        sheet.update(
            f"A{row_index}:D{row_index}",
            [[annotator_id, session_id, json_data, timestamp]]
        )
    else:
        sheet.append_row(
            [annotator_id, session_id, json_data, timestamp]
        )


def load_saved_annotations(annotator_id, session_id):
    try:
        sheet = get_sheet()
        records = sheet.get_all_records()
        for rec in records:
            if (str(rec.get("annotator_id")) == annotator_id
                    and rec.get("session_id") == session_id):
                loaded = json.loads(rec["full_json"])
                return {int(k): v for k, v in loaded.items()}
    except Exception as e:
        st.warning(f"Could not load saved progress: {e}")
    return None


# ============================================================
# HELPERS
# ============================================================
def get_display_order(annotator_id, prompt_index):
    seed = hash(f"{annotator_id}_{prompt_index}") % (2**32)
    rng = random.Random(seed)
    return rng.choice(["normal", "flipped"])


def empty_annotation(page_index, item, prompt_data, annotator_id):
    prompt_index = item["prompt"]
    order = get_display_order(annotator_id, prompt_index)

    story_a = prompt_data["system_a"][item["story_idx_a"]]
    story_b = prompt_data["system_b"][item["story_idx_b"]]
    raw_a = prompt_data.get("system_a_label", "system_a")
    raw_b = prompt_data.get("system_b_label", "system_b")

    if order == "normal":
        shown_as_a, shown_as_b = raw_a, raw_b
        left_story, right_story = story_a, story_b
    else:
        shown_as_a, shown_as_b = raw_b, raw_a
        left_story, right_story = story_b, story_a

    return {
        "page_index": page_index,
        "prompt_index": prompt_index,
        "shared": item.get("shared", False),
        "story_idx_a": item["story_idx_a"],
        "story_idx_b": item["story_idx_b"],
        "prompt": prompt_data["prompt"],
        "display_order": order,
        "system_a_label": shown_as_a,   # label of whichever system is on the LEFT
        "system_b_label": shown_as_b,   # label of whichever system is on the RIGHT
        "left_story": left_story,
        "right_story": right_story,
        "judgements": {dim["key"]: None for dim in COMPARISON_DIMENSIONS},
        "comments": "",
    }


# ============================================================
# UI COMPONENTS
# ============================================================
def render_story_card(label, story_text, bg_color, border_color):
    st.markdown(
        f"""<div style="
            background:{bg_color};
            border-top: 4px solid {border_color};
            border-radius: 10px;
            padding: 1rem 1.4rem 0.8rem 1.4rem;
            margin-bottom: 1rem;
        "><h3 style="margin:0 0 0.2rem 0; font-family:'Georgia',serif; color:#1a1a2e;">
            {label}
        </h3></div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div style="
            border-left: 3px solid {border_color};
            padding: 0.7rem 1rem;
            margin-bottom: 1rem;
            background: white;
            border-radius: 0 8px 8px 0;
        ">
            <div style="font-family:'Georgia',serif; font-size:0.97rem;
                line-height:1.7; color:#1a1a2e;">
                {story_text}
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_judgements(page_key, ann):
    st.markdown("---")
    st.markdown("## \u270d\ufe0f Your Judgements")
    if TIE_OPTION:
        st.caption("Pick which story performed better on each dimension, or choose Same if you can't tell them apart.")
    else:
        st.caption("Pick which story performed better on each dimension. You must choose one \u2014 no ties.")

    opts = ["Story A", "Story B"] + (["Same"] if TIE_OPTION else [])

    for dim in COMPARISON_DIMENSIONS:
        st.markdown(f"### {dim['label']}")
        st.caption(dim["description"])

        stored = ann["judgements"].get(dim["key"])
        if stored == "system_a":
            stored_display = "Story A"
        elif stored == "system_b":
            stored_display = "Story B"
        elif stored == "tie":
            stored_display = "Same"
        else:
            stored_display = None

        default_idx = opts.index(stored_display) if stored_display in opts else None

        choice = st.radio(
            dim["question"],
            opts,
            index=default_idx,
            horizontal=True,
            key=f"radio_{page_key}_{dim['key']}",
        )

        if choice is None:
            ann["judgements"][dim["key"]] = None
        elif choice == "Story A":
            ann["judgements"][dim["key"]] = "system_a"
        elif choice == "Story B":
            ann["judgements"][dim["key"]] = "system_b"
        else:
            ann["judgements"][dim["key"]] = "tie"

    st.markdown("#### Comments (optional)")
    ann["comments"] = st.text_area(
        "Any additional thoughts about these two stories?",
        value=ann.get("comments", ""),
        key=f"comments_{page_key}",
        height=100,
    )


# ============================================================
# EXPORT HELPER (run as: python app.py export)
# ============================================================
def export_assignments():
    data = load_data()
    total_prompts = len(data)
    needed = SHARED_COUNT + UNIQUE_COUNT * NUM_ANNOTATORS
    if total_prompts < needed:
        raise ValueError(
            f"Need at least {needed} prompts ({SHARED_COUNT} shared + "
            f"{UNIQUE_COUNT} x {NUM_ANNOTATORS} unique), but found {total_prompts}."
        )

    rng = random.Random(ASSIGNMENT_SEED)
    all_indices = list(range(total_prompts))
    rng.shuffle(all_indices)

    shared_prompts = sorted(all_indices[:SHARED_COUNT])
    remaining = all_indices[SHARED_COUNT:]

    def draw_story_indices(prompt_idx):
        # Seeded only by prompt index -> the same specific stories are shown
        # to every annotator who gets this prompt (needed for shared prompts
        # so inter-rater agreement is measured on identical material).
        r = random.Random(f"{ASSIGNMENT_SEED}_{prompt_idx}")
        return r.randrange(STORIES_PER_SET), r.randrange(STORIES_PER_SET)

    assignment_map = {}
    for i in range(NUM_ANNOTATORS):
        annotator_id = str(i + 1)
        unique_prompts = sorted(remaining[i * UNIQUE_COUNT:(i + 1) * UNIQUE_COUNT])
        assigned = [(p, True) for p in shared_prompts] + [(p, False) for p in unique_prompts]

        items = []
        for prompt_idx, is_shared in assigned:
            idx_a, idx_b = draw_story_indices(prompt_idx)
            items.append({
                "prompt": prompt_idx,
                "story_idx_a": idx_a,
                "story_idx_b": idx_b,
                "shared": is_shared,
            })

        order_rng = random.Random(f"{ASSIGNMENT_SEED}_order_{annotator_id}")
        order_rng.shuffle(items)

        assignment_map[annotator_id] = items

    with open("prompt_assignments.json", "w") as f:
        json.dump(assignment_map, f, indent=2)

    print("Saved prompt_assignments.json")
    for annotator_id, items in assignment_map.items():
        shared_n = sum(1 for it in items if it["shared"])
        print(f"Annotator {annotator_id}: {len(items)} items ({shared_n} shared, {len(items)-shared_n} unique)")


# ============================================================
# MAIN
# ============================================================
def main():
    st.set_page_config(
    page_title="Annotation Tool"
)

    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@300;400;500&display=swap');
        html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
        h1, h2, h3 { font-family: 'Lora', serif !important; }
        .stRadio > div { gap: 1rem; }
        </style>
    """, unsafe_allow_html=True)

    st.title("Pairwise Story Annotation")

    # with st.expander("\ud83d\udcd8 Instructions \u2014 read before starting", expanded=True):
    #     st.markdown(f"""
    #                     ### Welcome!

    #                     In each task you will:
    #                     1. Read a **writing prompt**.
    #                     2. Read **two short stories** (Story A and Story B), each written in response to that prompt.
    #                     3. Judge which story is higher **quality**{" \u2014 or mark them as Same" if TIE_OPTION else ", picking one, no ties"}:

    #                     | Dimension | What to consider |
    #                     |-----------|-----------------|
    #                     | **Quality** | Writing craft, coherence, originality, and how well it responds to the prompt |

    #                     > \u26a0\ufe0f Your progress is **auto-saved after each page**. If your session crashes, re-open the same URL and your work will be restored.
    #     """)
    with st.expander("📘 Instructions — read before starting", expanded=True):
        st.markdown(f"""
                        ### Welcome!

                        In each task you will:
                        1. Read a **writing prompt**.
                        2. Read **two short stories** (Story A and Story B), each written in response to that prompt.
                        3. Judge which story is higher **quality**{" — or mark them as Same" if TIE_OPTION else ", picking one, no ties"}:

                        | Dimension | What to consider |
                        |-----------|-----------------|
                        | **Quality** | "Consider writing craft, coherence, fluency, and how well it responds to the prompt." |

                        > ⚠️ Your progress is **auto-saved after each page**. If your session crashes, re-open the same URL and your work will be restored.
        """)

    # ---- Annotator ID ----
    query_params = st.query_params
    annotator_id = query_params.get("annotator", "")
    session_id   = query_params.get("session", "")

    if annotator_id not in VALID_ANNOTATOR_IDS:
        annotator_id = st.text_input(f"Enter your Annotator ID (1\u2013{NUM_ANNOTATORS})")
        if annotator_id not in VALID_ANNOTATOR_IDS:
            if annotator_id:
                st.error(f"Invalid ID. Must be one of: {', '.join(VALID_ANNOTATOR_IDS)}")
            st.stop()

    if not session_id:
        session_id = f"{annotator_id}_{uuid.uuid4().hex[:8]}"
        st.query_params.update(annotator=annotator_id, session=session_id)
        st.rerun()

    c1, c2 = st.columns(2)
    c1.info(f"**Annotator ID:** {annotator_id}")
    c2.info(f"**Session ID:** `{session_id}` \u2014 bookmark this URL to resume after a crash")

    # ---- Load data ----
    try:
        data = load_data()
    except FileNotFoundError:
        st.warning("\u26a0\ufe0f Data file not found. Showing demo data.")
        demo_a = [f"System A \u2014 Story {i+1}: Lorem ipsum dolor sit amet." for i in range(STORIES_PER_SET)]
        demo_b = [f"System B \u2014 Story {i+1}: Sed ut perspiciatis unde omnis." for i in range(STORIES_PER_SET)]
        data = [
            {
                "prompt": f"Demo prompt {i+1}: Write a story about something unexpected.",
                "system_a": demo_a, "system_b": demo_b,
                "system_a_label": "gt", "system_b_label": "model_x",
            }
            for i in range(100)
        ]

    # ---- Load assignment map from file ----
    try:
        assignment_map = load_assignment_map()
    except FileNotFoundError:
        st.error(
            f"\u274c Assignment file `{ASSIGNMENT_FILE}` not found. "
            "Run `python app.py export` to generate it first."
        )
        st.stop()

    if annotator_id not in assignment_map:
        st.error(f"\u274c Annotator ID `{annotator_id}` not found in `{ASSIGNMENT_FILE}`.")
        st.stop()

    assigned_items = assignment_map[annotator_id]
    total_pages    = len(assigned_items)

    # ---- Session state + crash recovery ----
    if "all_annotations" not in st.session_state:
        st.session_state.all_annotations = {}

    if "page" not in st.session_state:
        recovered = load_saved_annotations(annotator_id, session_id)
        if recovered:
            st.session_state.all_annotations = recovered
            resumed_page = total_pages - 1
            for i in range(total_pages):
                ann = recovered.get(i, {})
                missing = [d["key"] for d in COMPARISON_DIMENSIONS
                           if ann.get("judgements", {}).get(d["key"]) is None]
                if missing:
                    resumed_page = i
                    break
            st.session_state.page = resumed_page
            st.success(f"\u2705 Progress restored! Resuming at Task {resumed_page + 1} of {total_pages}.")
        else:
            st.session_state.page = 0

    current_page = st.session_state.page
    item = assigned_items[current_page]
    prompt_data  = data[item["prompt"]]

    if current_page not in st.session_state.all_annotations:
        st.session_state.all_annotations[current_page] = empty_annotation(
            current_page, item, prompt_data, annotator_id
        )

    ann = st.session_state.all_annotations[current_page]

    # ---- Progress bar ----
    st.progress(current_page / total_pages,
                text=f"Task {current_page + 1} of {total_pages}")

    # ---- Prompt banner ----
    st.markdown(
        f"""<div style="
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e8e8e8;
            border-radius: 14px;
            padding: 1.6rem 2rem;
            margin: 1rem 0 1.5rem 0;
            font-family: 'Lora', serif;
            font-size: 1.15rem;
            line-height: 1.6;
            border-left: 5px solid #e9a84c;
        ">
            <span style="font-size:0.75rem; text-transform:uppercase; letter-spacing:2px;
                color:#e9a84c; font-family:'DM Sans',sans-serif;">
                Prompt \u2014 Task {current_page + 1}
            </span><br><br>
            {prompt_data["prompt"]}
        </div>""",
        unsafe_allow_html=True,
    )

    # ---- Side-by-side single stories ----
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        render_story_card("Story A", ann["left_story"], "#f0f4ff", "#4a6fa5")
    with col_b:
        render_story_card("Story B", ann["right_story"], "#fff7f0", "#e9a84c")

    # ---- Judgements ----
    render_judgements(current_page, ann)

    # ---- Navigation ----
    st.markdown("---")
    nav1, _, nav3 = st.columns([1, 3, 1])
    is_last = current_page == total_pages - 1

    with nav1:
        if st.button("\u2b05\ufe0f Previous", disabled=(current_page == 0)):
            st.session_state.page -= 1
            st.rerun()

    with nav3:
        if not is_last:
            if st.button("Next \u27a1\ufe0f"):
                missing = [d["label"] for d in COMPARISON_DIMENSIONS
                           if ann["judgements"].get(d["key"]) is None]
                if missing:
                    st.error(f"Please answer all dimensions before continuing. Missing: {', '.join(missing)}")
                else:
                    # try:
                    #     save_annotations(annotator_id, session_id,
                    #                      st.session_state.all_annotations)
                    # except Exception:
                    #     pass
                    # st.session_state.page += 1
                    # st.rerun()
                    try:
                        save_annotations(
                            annotator_id,
                            session_id,
                            st.session_state.all_annotations
                        )
                        st.success("Progress saved!")
                    except Exception as e:
                        st.error(
                            f"Autosave failed: {type(e).__name__}: {repr(e)}"
                        )
                        st.stop()

                    st.session_state.page += 1
                    st.rerun()

    # ---- Submit ----
    if is_last:
        st.markdown("### \ud83c\udfc1 Ready to submit?")
        if st.button("\u2705 Submit All Annotations", type="primary", use_container_width=True):
            all_complete = True
            for i in range(total_pages):
                if i not in st.session_state.all_annotations:
                    st.error(f"Task {i + 1} has not been completed \u2014 please go back and fill it in.")
                    all_complete = False
                    continue
                a = st.session_state.all_annotations[i]
                missing_labels = [d["label"] for d in COMPARISON_DIMENSIONS
                                  if a["judgements"].get(d["key"]) is None]
                if missing_labels:
                    st.error(f"Task {i + 1} is missing judgements for: {', '.join(missing_labels)}")
                    all_complete = False

            if all_complete:
                try:
                    save_annotations(annotator_id, session_id,
                                     st.session_state.all_annotations)
                    st.success("\u2705 All annotations saved! Thank you!")
                    st.balloons()
                except Exception as e:
                    st.error(
                        f"Save failed: {e}. Please screenshot your answers and "
                        "contact the study coordinator."
                    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        export_assignments()
    else:
        main()