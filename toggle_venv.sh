#!/usr/bin/env bash
# Toggle this repo's .venv in your *current* shell (must be sourced, not executed).
#
#   source ./toggle_venv.sh        # bash
#   . ./toggle_venv.sh             # bash or zsh
#
# Tip: add an alias in ~/.bashrc:
#   alias httptoggle='source ~/http-validator/toggle_venv.sh'

if [[ -n "${ZSH_VERSION:-}" ]]; then
  _here="${(%):-%x}"
  # zsh: sourced if context ends with :file
  if [[ "${ZSH_EVAL_CONTEXT:-}" != *:file ]]; then
    echo "Source this file from zsh:" >&2
    echo "  . ${PWD}/toggle_venv.sh" >&2
    exit 1
  fi
elif [[ -n "${BASH_VERSION:-}" ]]; then
  _here="${BASH_SOURCE[0]}"
  if [[ "$_here" == "$0" ]]; then
    echo "Source this file from bash:" >&2
    echo "  source ${PWD}/toggle_venv.sh" >&2
    exit 1
  fi
else
  echo "Use bash or zsh and source this file." >&2
  exit 1
fi

_repo="$(cd "$(dirname "$_here")" && pwd)"
_venv="$_repo/.venv"

if [[ -n "${VIRTUAL_ENV:-}" && "$VIRTUAL_ENV" == "$_venv" ]]; then
  deactivate
  echo "Deactivated: $_venv"
elif [[ -f "$_venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$_venv/bin/activate"
  echo "Activated: $_venv"
else
  echo "No venv at $_venv" >&2
  echo "Create it:  cd $_repo && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
fi

unset _here _repo _venv