"""Entry point so `python -m kubekeeper.operator` runs the kopf operator."""
import kopf

import kubekeeper.operator.main  # noqa: F401 — registers kopf handlers


def main() -> None:
    kopf.run()


if __name__ == "__main__":
    main()
