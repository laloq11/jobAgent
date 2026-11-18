FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive

# Python, LaTeX (build_pdf: pdflatex + pdfinfo), git
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    openssh-client \
    python3 \
    python3-pip \
    sqlite3 \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies: requirements.txt at the repo root is the single list
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Claude Code CLI (scoring, drafting, PhD web search)
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"
