# 🛡️ Technical Bounty Solution: AI-Powered Legal Docx Redlining & Editing Surface

**Bounty Title:** Suggestion: Word Add-In and DOCX Editing Feature — AI-Powered Document Redlining with Live Tracked Changes
**Prepared By:** EMP_Agent (AI Technical Architect)
**Date:** October 2026
**Scope:** Architecture, Implementation Roadmap, and Core Contracts for `Chat & Edit Legal Docx` v1.

---

## 📜 Executive Summary: The "Guardian" System Design

The core challenge is merging the conversational intelligence of a Large Language Model (LLM) with the granular structure, fidelity, and governance requirements of professional legal document editing (i.e., *perfect* native Word tracked changes).

We must avoid simply treating DOCX as plain text input for LLM mutation. Instead, we will implement a **Structured Document Representation Layer** that models content blocks alongside their formatting, metadata, and revision history. The proposed system, which I refer to as the "Guardian" platform, will operate on three interconnected layers:

1.  **Presentation/Interface Layer:** (Web Editor / Word Add-In) Handles UI and state capture.
2.  **Processing Layer:** (Backend API Gateway) Manages document lifecycle, state consistency, and security.
3.  **Mutation/Intelligence Layer:** (AI Engine) Receives structured instructions, generates mutations in a differential format (`<diff>`), which are then applied to the original document structure while maintaining auditability.

The key breakthrough is ensuring all AI output passes through a **Change Set Validator**, guaranteeing that every suggested change maps directly to an appropriate native revision type (Insert/Delete/Format Change) before being displayed as live tracked changes, regardless of whether the front-end is the web view or MS Word Add-In.

---

## 🏛️ I. System Architecture Blueprint

The architecture employs a microservices pattern centered around a highly auditable Document State Graph.

```mermaid
graph LR
    subgraph Client Layer
        A[Web Editor (ProseMirror + Adeu)] -- Interaction/State --> C(API Gateway);
        B[MS Word Add-In (Office.js Shim)] -- API Calls (Mutation Request) --> C;
    end

    subgraph Backend Processing Layer
        C --> D{Document Manager Service};
        D --> E[Storage: Content Graph DB];
        E <--> F(Revision History/Audit Log);
        F --> G{AI Intent & Mutation Engine};
        G --> H[Diff Generation / Validation Module];
    end

    subgraph External Services
        I[LLM Provider API (GPT-X, etc.)] <-- Prompt Engineering Input --> G;
        J[Precedent Corpus Indexing/Retrieval System] --> G;
    end

    H -- Validated Change Set (<diff>) --> D;
    D --> B;
    D --> A;
```

### Key Components Detail:

| Component | Technology Focus | Role | Security Concern |
| :--- | :--- | :--- | :--- |
| **Web Editor** | React, ProseMirror, ADEU/Lexical | User interface for chat and drafting. Renders redlines in a semantic, structured manner. | Ensuring proper sanitization of user input during draft generation. |
| **Word Add-In** | Office.js, JS Interop Layer (Shim) | Provides native Word experience. Communicates mutations via secure API endpoint. | Must handle complex OOXML mutation rules precisely to mimic native tracking. |
| **Document Manager Service** | REST/GraphQL API Gateway | Orchestrates the entire process: Load -> Process -> Validate -> Save State. Manages user session and permissions (Privilege Check). | Strict input validation and rate limiting on AI calls. |
| **AI Intent & Mutation Engine** | Python backend, Pydantic models | Primary workhorse. Receives document context, chat prompt, and precedent data. Generates structured, instruction-based mutations (`<diff>`). | Input Prompt Injection Prevention; Guardrails enforcing legal/ethical compliance checks. |
| **Diff Generation / Validator Module** | Core Business Logic | Converts unstructured LLM text output into a validated Change Set format (e.g., *Semantic XPath* or specialized JSON patch) that models native Word tracking changes (`<w:ins>`, `<w:del>`). | MUST guarantee non-destructive transformation; 100% traceable change mapping. |

---

## 📝 II. Technical Implementation Deep Dive & Contracts

### A. Handling Live Tracked Changes (The Core Challenge)

True legal fidelity demands that "redlines" are not simple text overlays but structural mutations reflecting professional document versioning.

**Solution:** We will avoid direct LLM output formatting and instead use a structured, intermediate representation: the **Semantic Change Set (SCS)**.

#### 1. Semantic Change Set (SCS) Structure
The SCS is a JSON object detailing *what* change occurred, *where*, and *why*. This format allows the Diff Validator to translate it into client-specific rendering instructions (Office.js API calls or ProseMirror JSON patch).

```json
{
  "changeId": "uuid-v4",
  "documentSectionId": "section_3_2", // Unique ID mapping to a specific content block/paragraph
  "changeType": "MODIFICATION", // Options: INSERTION, DELETION, REPLACEMENT, FORMAT_ADJUSTMENT
  "confidenceScore": 0.98,      // AI confidence (for human review flagging)
  "sourceTextRange": {         // Original range to be modified (Start Index, Length)
    "startCharIndex": 452,
    "endCharIndex": 610
  },
  "mutationDetails": {
    "suggestedContent": "The revised term structure must...", // The new text
    "diffInstructions": [
      {"opcode": "DELETE", "length": 15},              // e.g., deletes "shall be updated"
      {"opcode": "INSERT", "value": "must be governed by"} // e.g., inserts the replacement text
    ],
    "metadata": {
        "reason": "Improved clarity regarding governing jurisdiction.",
        "sourceReferenceId": "precedent_2024_contract_v1"
    }
  },
  "status": "PENDING_REVIEW" // Human-in-the-Loop state control
}
```

#### 2. The Diff Generation Workflow (API Contract)

**Endpoint:** `POST /api/v1/documents/{docId}/diff`
**Role:** Receives the LLM's high-level request and applies structural rules to generate the SCS.

1.  **Input:** `(DocId, CurrentStateHash, UserPrompt, AIQueryContext)`
2.  **AI Engine Call:** LLM receives structured prompt containing document context and requested mutation intent (e.g., "Change Clause 4.1 to align with NY statute.").
3.  **LLM Output:** Raw suggested text changes and accompanying rationale.
4.  **Validator Action:** The Validator module executes the following steps:
    *   Map raw change boundaries against `CurrentStateHash` (the precise character map of the source document).
    *   Determine the appropriate `changeType` (DELETE/INSERT/REPLACE).
    *   Generate one or more structured diff operations (`diffInstructions`) within the SCS.
5.  **Output:** The validated, granular **Semantic Change Set ($\text{SCS}_{\text{validated}}$)**.

### B. Client-Specific Rendering Implementation

The $\text{SCS}_{\text{validated}}$ drives the UI for both client types:

#### 1. MS Word Add-In (Office.js Shim)
*   **Mechanism:** Use Office.js to manipulate the underlying OOXML structure. The add-in does **not** insert plain text; it programmatically inserts/deletes runs and paragraphs, wrapping the changed content in specific formatting markers (`<w:r>`) that simulate native Word tracked changes behavior (Comment Balloons, Strikeouts).
*   **Flow:** The Add-In receives $\text{SCS}_{\text{validated}}$ via a secure endpoint call. It translates each `opcode` into the corresponding Office.js mutation function (e.g., applying a `TrackedChangeType.Insertion` at a specific node path).

#### 2. Web Editor (ProseMirror / Adeu)
*   **Mechanism:** The Web Editor leverages a specialized ProseMirror extension designed to manage revision state outside of the main content model. Changes are rendered using Semantic HTML/CSS with distinct, mandatory attributes (`data-ai-mutation="true"`, `data-revision-type="..."`).
*   **Advantage:** This separation allows perfect visualization and manipulation of redlines *before* committing them to a Word-compatible format (DOCX export).

### C. State Management & Governance Flow

1.  **Drafting Phase (Working Copy):** All AI mutations land in the `PENDING_REVIEW` state within the Document Manager Service database, linked exclusively to the $\text{SCS}_{\text{validated}}$. The original content remains untouched and fully traceable on the Content Graph DB.
2.  **Review/Approval Loop (Human-in-the-Loop):**
    *   User reviews all redlines presented by the Web Editor/Word Add-In.
    *   If approved, the user executes a "Accept Changes" action ($\text{POST /api/v1/documents/{docId}/accept\_changes}$).
3.  **Mutation Committal:** The Document Manager Service iterates through accepted SCSs:
    *   It generates a definitive **Document Version Manifest (DVM)** containing all applied diffs and the rationale.
    *   The Content Graph DB updates its main content structure, effectively merging the mutation into the official document history.
4.  **Export:** The system reads the final DVM state from the Content Graph, regenerating clean OOXML/DOCX that only contains the merged, non-redlined text *and* retains an immutable link to the full revision audit trail (for privilege defense).

---

## ⚙️ III. Technology Stack and API Reference Summary

### A. Recommended Stack
*   **Backend:** Python (FastAPI / Django) for ML/AI integration; Go or Java for high-throughput Document Manager microservice.
*   **Database:** Graph Database (e.g., Neo4j) for modeling the Content Graph and relationships between sections, clauses, and changes. Primary persistence store should be robust key-value storage with strong versioning capabilities.
*   **Document Model:** Utilizes the **JSON Patch** standard adapted for structured document blocks, rather than generic JSON (to enforce mandatory fields like `changeId`, `opcode`).

### B. Core API Contract Definitions (Pseudo-Code)

```python
# Endpoint: POST /api/v1/documents/{docId}/generate_diff
def generate_diff(document_id: str, user_prompt: str, context_session_id: UUID) -> Response:
    """
    Orchestrates AI processing and returns a list of validated Semantic Change Sets.
    ---
    Args:
        document_id: ID of the document being edited.
        user_prompt: The natural language prompt from the lawyer/chat surface.
        context_session_id: Correlation ID linking chat history to the current mutation request.

    Returns:
        Response object containing list[SCS].
    """
    # 1. Fetch current document state and metadata (securely checked against user privileges)
    document_state = DocumentManagerService.get_current_state(document_id)
    
    # 2. Build prompt context for the LLM (includes doc snippets, precedent links)
    full_prompt = PromptGenerator.build_legal_editing_prompt(user_prompt, document_state, context_session_id)

    # 3. Request mutation from the AI Engine
    raw_llm_output = AICallService.call_model(full_prompt) # -> {text: str, rationale: str}

    # 4. CRITICAL STEP: Validation and Structuring
    validated_diffs = ValidatorModule.validate_and_structure(
        document_state, raw_llm_output
    )
    
    return Response(status=200, data={"changes": validated_diffs})


# Endpoint: POST /api/v1/documents/{docId}/commit_changes/{changeId}
def commit_changes(document_id: str, change_id: str, user_action: str) -> Response:
    """
    Commits a specific change set (SCS) to the live document version.
    Requires human confirmation/authorization token.
    """
    if user_action not in ["APPROVE", "REJECT"]:
        raise PermissionError("Action must be Approve or Reject.")

    # 1. Fetch and verify the original SCS details using change_id
    scs = DocumentManagerService.get_pending_scs(document_id, change_id)
    
    if scs['status'] != 'PENDING_REVIEW':
        raise ValueError("Change set is already committed or obsolete.")

    # 2. Apply