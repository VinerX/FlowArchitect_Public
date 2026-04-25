import os
import sys
import json
import re
import unicodedata as ud
from collections import Counter
from main_logger import logger

def save_combined_messages(combined_messages, output_folder="SavedMessages"):
    os.makedirs(output_folder, exist_ok=True)
    file_name = "combined_messages.json"
    file_path = os.path.join(output_folder, file_name)
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(combined_messages, file, ensure_ascii=False, indent=4)
    logger.info(f"Сообщения сохранены в файл: {file_path}")


def calculate_cost_for_combined_messages(self, combined_messages, cost_input_per_1000):
    token_count = self.count_tokens(combined_messages)
    cost = (token_count / 1000) * cost_input_per_1000
    return f"Токенов {token_count} Цена {cost}"


def count_tokens(self, messages):
    return sum(
        len(self.tokenizer.encode(msg["content"])) for msg in messages
        if isinstance(msg, dict) and "content" in msg
    )


def SH(s, placeholder="***", percent=0.20):
    """
    Сокращает строку, оставляя % символов в начале и % в конце.
    Средняя часть заменяется на placeholder.
    """
    if not s:
        return s

    length = len(s)
    visible_length = max(1, int(length * percent))  # Минимум 1 символ

    start = s[:visible_length]
    end = s[-visible_length:]
    return f"{start}{placeholder}{end}"


def shift_chars(s, shift):
    """
    Сдвигает все символы в строке на заданное число.
    :param s: Исходная строка.
    :param shift: Число, на которое нужно сдвинуть символы.
    :return: Зашифрованная или расшифрованная строка.
    """
    result = []
    for char in s:
        new_char = chr(ord(char) + shift)
        result.append(new_char)
    return ''.join(result)


def render_qss(template: str, variables: dict) -> str:
    """
    Рендерит QSS/CSS-шаблон, заменяя плейсхолдеры вида {name} на значения из словаря variables.
    - Не трогает обычные блочные скобки QSS ({ ... }), т.к. матчится только на {слово}.
    - Если ключ не найден в словаре — плейсхолдер остаётся без изменений.

    :param template: Строка QSS/СSS с плейсхолдерами {var}.
    :param variables: Словарь с заменами.
    :return: Рендеренная строка.
    """
    if not isinstance(template, str):
        template = str(template)
    if not isinstance(variables, dict):
        raise TypeError("variables must be a dict")

    pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def _repl(m: re.Match) -> str:
        key = m.group(1)
        return str(variables.get(key, m.group(0)))

    return pattern.sub(_repl, template)