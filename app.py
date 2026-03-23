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
STORIES_PER_SET = 10
NUM_ANNOTATORS = 10

# Prompts 0–69  → single coverage (1 annotator each)
# Prompts 70–99 → triple coverage (3 annotators each)
# Total slots: 70×1 + 30×3 = 160 → 16 prompts per annotator
SINGLE_COVERAGE_END   = 70   # prompts [0, 70) seen by 1 annotator
TRIPLE_COVERAGE_START = 70   # prompts [70, 100) seen by 3 annotators
ASSIGNMENT_SEED = 42          # change this to reshuffle assignments

COMPARISON_DIMENSIONS = [
    {
        "key": "diversity",
        "label": "Diversity",
        "question": "Which set of stories is more diverse?",
        "description": "Consider variety in themes, styles, narrative approaches, and ideas across the stories.",
    },
    {
        "key": "quality",
        "label": "Quality",
        "question": "Which set of stories is higher quality?",
        "description": "Consider writing craft, coherence, originality, and how well each story responds to the prompt.",
    },
    {
        "key": "creativity",
        "label": "Overall Creativity",
        "question": "Which set of stories is more creative overall?",
        "description": "Consider imaginative use of the prompt, unexpected ideas, and creative risk-taking.",
    },
]

TIE_OPTION = False
SHEET_NAME = "creative_writing_pairwise_annotations"
DATA_FILE  = "./merged_generations.json"

VALID_ANNOTATOR_IDS = [str(i) for i in range(1, NUM_ANNOTATORS + 1)]


# ============================================================
# ASSIGNMENT LOGIC
# ============================================================
@st.cache_data
def build_assignment_map(num_prompts):
    """
    Returns dict: annotator_id (str) -> list of prompt indices (ints).

    Single-coverage prompts appear once in the slot pool.
    Triple-coverage prompts appear three times.
    The pool is shuffled with a fixed seed then split evenly across annotators.
    Result: 16 prompts per annotator, every prompt covered the right number of times.
    """
    single_prompts = list(range(SINGLE_COVERAGE_END))
    triple_prompts = list(range(TRIPLE_COVERAGE_START, num_prompts))

    slots = single_prompts[:]
    for p in triple_prompts:
        slots.extend([p, p, p])

    rng = random.Random(ASSIGNMENT_SEED)
    rng.shuffle(slots)

    chunk = len(slots) // NUM_ANNOTATORS
    return {
        str(i + 1): slots[i * chunk: (i + 1) * chunk]
        for i in range(NUM_ANNOTATORS)
    }


# ============================================================
# DATA LOADING
# ============================================================
@st.cache_data
def load_data():
    """
    Expected JSON — list of prompt objects:
    [
      {
        "prompt": "Write a story about...",
        "system_a": ["story1", ...],   <- STORIES_PER_SET items
        "system_b": ["story1", ...],
        "system_a_label": "gt",        <- backend label, hidden from annotators
        "system_b_label": "model_x"
      },
      ...
    ]
    """
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


def save_annotations(annotator_id, session_id, all_data):
    sheet = get_sheet()
    serializable = {str(k): v for k, v in all_data.items()}
    json_data = json.dumps(serializable)
    timestamp = datetime.datetime.now().isoformat()

    rows = sheet.get_all_values()
    row_index = None
    for idx, row in enumerate(rows[1:], start=2):
        if row[0] == annotator_id and row[1] == session_id:
            row_index = idx
            break

    if row_index:
        sheet.update(f"A{row_index}:D{row_index}",
                     [[annotator_id, session_id, json_data, timestamp]])
    else:
        sheet.append_row([annotator_id, session_id, json_data, timestamp])


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


def empty_annotation(prompt_index, annotator_id, prompt_data):
    order = get_display_order(annotator_id, prompt_index)
    raw_a = prompt_data.get("system_a_label", "system_a")
    raw_b = prompt_data.get("system_b_label", "system_b")
    # system_a_label/system_b_label store what the annotator ACTUALLY SAW
    # in each column. When flipped, the two systems swap columns.
    shown_as_a, shown_as_b = (raw_a, raw_b) if order == "normal" else (raw_b, raw_a)
    return {
        "prompt_index": prompt_index,
        "prompt": prompt_data["prompt"],
        "display_order": order,
        "system_a_label": shown_as_a,  # what was in the System A column
        "system_b_label": shown_as_b,  # what was in the System B column
        "judgements": {dim["key"]: None for dim in COMPARISON_DIMENSIONS},
        "comments": "",
    }


# ============================================================
# UI COMPONENTS
# ============================================================
def render_story_set(label, stories, bg_color, border_color):
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
    for i, story in enumerate(stories[:STORIES_PER_SET]):
        st.markdown(
            f"""<div style="
                border-left: 3px solid {border_color};
                padding: 0.7rem 1rem;
                margin-bottom: 1rem;
                background: white;
                border-radius: 0 8px 8px 0;
            ">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:1.5px;
                    color:#888; margin-bottom:0.4rem; font-family:'DM Sans',sans-serif;">
                    Story {i + 1}
                </div>
                <div style="font-family:'Georgia',serif; font-size:0.97rem;
                    line-height:1.7; color:#1a1a2e;">
                    {story}
                </div>
            </div>""",
            unsafe_allow_html=True,
        )


def render_judgements(page_key, ann):
    st.markdown("---")
    st.markdown("## ✍️ Your Judgements")
    st.caption("Pick which set performed better on each dimension. You must choose one — no ties.")

    # Judgements are stored simply as "system_a" or "system_b" meaning
    # the annotator picked the System A or System B column respectively.
    # system_a_label / system_b_label in the annotation already record
    # which real system (e.g. llama_ft or baco) was in each column,
    # so no further decoding is needed at analysis time.
    opts = ["System A", "System B"]

    for dim in COMPARISON_DIMENSIONS:
        st.markdown(f"### {dim['label']}")
        st.caption(dim["description"])

        stored = ann["judgements"].get(dim["key"])
        # stored is "system_a", "system_b", or None — maps 1:1 to column label
        if stored == "system_a":
            stored_display = "System A"
        elif stored == "system_b":
            stored_display = "System B"
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
        elif choice == "System A":
            ann["judgements"][dim["key"]] = "system_a"
        else:
            ann["judgements"][dim["key"]] = "system_b"

    st.markdown("#### 💬 Comments (optional)")
    ann["comments"] = st.text_area(
        "Any additional thoughts about these two sets?",
        value=ann.get("comments", ""),
        key=f"comments_{page_key}",
        height=100,
    )


# ============================================================
# MAIN
# ============================================================
def main():
    st.set_page_config(
        page_title="Pairwise Story Annotation",
        page_icon="📝",
        layout="wide",
    )

    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@300;400;500&display=swap');
        html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
        h1, h2, h3 { font-family: 'Lora', serif !important; }
        .stRadio > div { gap: 1rem; }
        </style>
    """, unsafe_allow_html=True)

    st.title("📝 Pairwise Story Annotation")

    with st.expander("📘 Instructions — read before starting", expanded=True):
        st.markdown(f"""
### Welcome!

In each task you will:
1. Read a **writing prompt**.
2. Read **two sets of {STORIES_PER_SET} short stories** (System A and System B), each written in response to that prompt.
3. Judge which set is better on **three dimensions** — you must pick one, no ties:

| Dimension | What to consider |
|-----------|-----------------|
| **Diversity** | Variety in themes, styles, narrative approaches, and ideas across the stories |
| **Quality** | Writing craft, coherence, originality, and responsiveness to the prompt |
| **Overall Creativity** | Imaginative use of the prompt, unexpected ideas, creative risk-taking |

> ⚠️ Your progress is **auto-saved after each page**. If your session crashes, re-open the same URL and your work will be restored.
        """)

    # ---- Annotator ID ----
    query_params = st.query_params
    annotator_id = query_params.get("annotator", "")
    session_id   = query_params.get("session", "")

    if annotator_id not in VALID_ANNOTATOR_IDS:
        annotator_id = st.text_input(f"Enter your Annotator ID (1–{NUM_ANNOTATORS})")
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
    c2.info(f"**Session ID:** `{session_id}` — bookmark this URL to resume after a crash")

    # ---- Load data ----
    try:
        data = load_data()
    except FileNotFoundError:
        st.warning("⚠️ Data file not found. Showing demo data.")
        demo_a = [f"System A — Story {i+1}: Lorem ipsum dolor sit amet." for i in range(STORIES_PER_SET)]
        demo_b = [f"System B — Story {i+1}: Sed ut perspiciatis unde omnis." for i in range(STORIES_PER_SET)]
        data = [
            {
                "prompt": f"Demo prompt {i+1}: Write a story about something unexpected.",
                "system_a": demo_a, "system_b": demo_b,
                "system_a_label": "gt", "system_b_label": "model_x",
            }
            for i in range(100)
        ]

    # ---- Build assignment map ----
    assignment_map  = build_assignment_map(len(data))
    assigned_indices = assignment_map[annotator_id]
    total_pages      = len(assigned_indices)

    # ---- Session state + crash recovery ----
    if "all_annotations" not in st.session_state:
        st.session_state.all_annotations = {}

    if "page" not in st.session_state:
        recovered = load_saved_annotations(annotator_id, session_id)
        if recovered:
            st.session_state.all_annotations = recovered
            resumed_page = total_pages - 1
            for i, pidx in enumerate(assigned_indices):
                ann = recovered.get(pidx, {})
                missing = [d["key"] for d in COMPARISON_DIMENSIONS
                           if ann.get("judgements", {}).get(d["key"]) is None]
                if missing:
                    resumed_page = i
                    break
            st.session_state.page = resumed_page
            st.success(f"✅ Progress restored! Resuming at Task {resumed_page + 1} of {total_pages}.")
        else:
            st.session_state.page = 0

    current_page = st.session_state.page
    prompt_index = assigned_indices[current_page]
    prompt_data  = data[prompt_index]

    if prompt_index not in st.session_state.all_annotations:
        st.session_state.all_annotations[prompt_index] = empty_annotation(
            prompt_index, annotator_id, prompt_data
        )

    ann   = st.session_state.all_annotations[prompt_index]
    order = ann["display_order"]

    # Labels are always System A (left) and System B (right).
    # Only the underlying stories swap — system_b data shows under "System A" when flipped.
    left_label, right_label = "System A", "System B"
    if order == "normal":
        left_stories, right_stories = prompt_data["system_a"], prompt_data["system_b"]
    else:
        left_stories, right_stories = prompt_data["system_b"], prompt_data["system_a"]

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
                Prompt — Task {current_page + 1}
            </span><br><br>
            {prompt_data["prompt"]}
        </div>""",
        unsafe_allow_html=True,
    )

    # ---- Side-by-side stories ----
    col_a, col_b = st.columns(2, gap="large")
    with col_a:
        render_story_set(left_label, left_stories, "#f0f4ff", "#4a6fa5")
    with col_b:
        render_story_set(right_label, right_stories, "#fff7f0", "#e9a84c")

    # ---- Judgements ----
    render_judgements(prompt_index, ann)

    # ---- Navigation ----
    st.markdown("---")
    nav1, _, nav3 = st.columns([1, 3, 1])
    is_last = current_page == total_pages - 1

    with nav1:
        if st.button("⬅️ Previous", disabled=(current_page == 0)):
            st.session_state.page -= 1
            st.rerun()

    with nav3:
        if not is_last:
            if st.button("Next ➡️"):
                missing = [d["label"] for d in COMPARISON_DIMENSIONS
                           if ann["judgements"].get(d["key"]) is None]
                if missing:
                    st.error(f"Please answer all dimensions before continuing. Missing: {', '.join(missing)}")
                else:
                    try:
                        save_annotations(annotator_id, session_id,
                                         st.session_state.all_annotations)
                    except Exception:
                        pass
                    st.session_state.page += 1
                    st.rerun()

    # ---- Submit ----
    if is_last:
        st.markdown("### 🏁 Ready to submit?")
        if st.button("✅ Submit All Annotations", type="primary", use_container_width=True):
            all_complete = True
            for task_num, pidx in enumerate(assigned_indices):
                if pidx not in st.session_state.all_annotations:
                    st.error(f"Task {task_num + 1} has not been completed — please go back and fill it in.")
                    all_complete = False
                    continue
                a = st.session_state.all_annotations[pidx]
                missing_labels = [d["label"] for d in COMPARISON_DIMENSIONS
                                  if a["judgements"].get(d["key"]) is None]
                if missing_labels:
                    st.error(f"Task {task_num + 1} is missing judgements for: {', '.join(missing_labels)}")
                    all_complete = False

            if all_complete:
                try:
                    save_annotations(annotator_id, session_id,
                                     st.session_state.all_annotations)
                    st.success("✅ All annotations saved! Thank you!")
                    st.balloons()
                except Exception as e:
                    st.error(
                        f"Save failed: {e}. Please screenshot your answers and "
                        "contact the study coordinator."
                    )


if __name__ == "__main__":
    main()