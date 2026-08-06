# Loreboard

Loreboard is a full-stack web app that automates the acquisition, analysis, and vectorization of fantasy art for a cross-modal recommendation system and image property visualization. The project's architecture is designed to be modular and scalable, showcasing best practices in data engineering, backend development, and AI model integration.

## Core Features/Technical Stack

- **Automated Data Pipeline**: A multi-stage process that scrapes and classifies image data from DeviantArt and ArtStation using the Contrastive Language-Image Pretraining (CLIP) model from [OpenAI](https://github.com/openai/CLIP).

- **LLM Metadata Generation**: Utilizes the Gemini API (`gemini-1.5-flash`) to generate captions, titles, tags, and analytical scores for all visual content, stored in a SQLite database.

- **Cross-Modal Vector Search**: Leverages a ChromaDB vector database to recommend music based on the semantic meaning of visual art embeddings.

- **Backend**: Uses FastAPI with RESTful API endpoints to serve the frontend and provide static file access to the image and audio datasets.

- **Frontend**: A Javascript UI featuring an infinite-scroll gallery, a favorites system, and a `Chart.js` dashboard for visualizing the metadata of a user's collection.

## Future Developmenet

**Phase 1: Apache Infrastructure and MLOps**

- **Pipeline Orchestration:** Refactor the data pipeline scripts into a DAG managed by Apache Airflow, enabling scheduled runs, automated retries, and robust monitoring.

- **Event-Driven Architecture:** Implement Apache Kafka to transition from batch processing to a real-time system where new content is process via a producer/consumer model.

- **Containerization:** Containerize all services using Docker and manage the environment with Docker Compose for deployment and scalability.

**Phase 2: Finetuning and Model Specialization**

- **Custom Classifier:** Finetune the CLIP model on a domain-specific dataset to improve the accuracy of the art classification and curation stage.

- **Specialized LLM:** Finetune Llama 3 8B on caption data to create a stylistically consistent model for metadata generation.

- **Custom Embedding Model:** Finetune a bi-modal embedding model using contrastive learning to optimize the vector space for the specific task of matching visual art with music, thereby increasing recommendation relevance.

**Phase 3: Advanced Generative Features**

- **Generative Storytelling** Implement a feature where the system arranges a user-selected set of images into a narrative arc.

    - An LLM will determine the story sequence and generate transition text.
    - A finetuned diffusion model will generate visual transitions between the images.
    - The system will dynamically edit and blend the associated audio tracks to create a continuous, cinematic soundtrack for the generated story.