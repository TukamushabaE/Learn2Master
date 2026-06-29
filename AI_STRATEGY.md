# Learn2Master AI Strategy & Roadmap

This document outlines the "best-in-class" AI implementation strategy for the Learn2Master platform, focusing on the Uganda Competency-Based Curriculum (CBC).

## 1. Core AI Models

### Knowledge Tracing: BKT + DKT
- **Bayesian Knowledge Tracing (BKT)**: Currently implemented in `engine.py`. Provides explainable, rule-based mastery updates. Best for immediate student/teacher feedback.
- **Deep Knowledge Tracing (DKT)**: Recommended for phase 2. Uses RNNs (LSTMs) or Transformers to predict future student performance across disparate subjects by capturing complex learning patterns.

### Generative AI: RAG Pipeline
- **Model**: GPT-4o, Llama 3, or Mistral-7B.
- **Retrieval-Augmented Generation (RAG)**: Ground the LLM in the Uganda National Curriculum Development Centre (NCDC) syllabus.
- **Implementation**: Convert learning outcomes and notes into vector embeddings (using OpenAI `text-embedding-3-small`) and store them in a vector database like Pinecone.

### Multimodal Evidence Assessment
- **Model**: GPT-4-Vision or Gemini Pro.
- **Purpose**: Automatically analyze student-submitted practical evidence (photos of experiments, screenshots of code) against CBC performance indicators.

## 2. Implementation Roadmap

### Phase 1: Context-Aware Rule Engine (Current)
- BKT-based mastery calculation.
- Rule-based "AI Assistant" that uses student mastery data and knowledge gap analysis to provide semi-personalized guidance.

### Phase 2: Integrated LLM Tutor
- Implement a `/v1/chat/completions` proxy to an LLM provider.
- Inject student context (mastery profile, recent activity) into the system prompt.
- Add RAG to ensure the tutor only provides curriculum-aligned help.

### Phase 3: Predictive Analytics & Multimodal
- Deploy DKT models to identify students "at risk" of falling behind before it happens.
- Implement automated evidence grading using vision-language models.

## 3. Ethical AI & CBC Alignment
- **Explainability**: All AI-driven mastery changes must include a human-readable "Reasoning" string (as seen in `AttemptLog`).
- **Bias Mitigation**: Ensure training data for DKT/LLM includes diverse regional contexts from within Uganda.
