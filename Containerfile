# PyAutopsy container image.
#
# Bakes the native forensic libraries (sleuthkit + libewf) plus their -dev
# headers so that BOTH raw/dd and E01/EWF ingest work out of the box -- the host
# this was developed on lacks libewf-dev, so the container is the reference
# environment for full E01 support (D-13, 01-RESEARCH.md Environment Availability).
FROM fedora:41

# Native forensic libraries + build toolchain.
#   sleuthkit / sleuthkit-devel -> libtsk (pytsk3)
#   libewf / libewf-devel       -> libewf (libewf-python / pyewf, the [ewf] extra)
RUN dnf install -y --setopt=install_weak_deps=False \
        python3 python3-pip python3-devel \
        sleuthkit sleuthkit-devel \
        libewf libewf-devel \
        gcc gcc-c++ \
    && dnf clean all

WORKDIR /opt/pyautopsy

# Copy project metadata + sources, then install with the E01 (ewf) extra so the
# container has full raw + E01 support.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir ".[ewf]"

# Run as a non-root user; evidence should be mounted read-only at runtime.
RUN useradd --create-home --uid 1000 analyst
USER analyst
WORKDIR /home/analyst

ENTRYPOINT ["pyautopsy"]
CMD ["--help"]
