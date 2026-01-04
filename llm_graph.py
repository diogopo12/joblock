# Joblock - Invisible AI Overlay Assistant
# Copyright (C) 2026 Diogo Pasi de Oliveira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import base64
from openai import OpenAI

client = OpenAI()

def ask_llm(prompt: str, image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    resp = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        # ✅ Base64 como Data URL (campo correto é image_url)
                        "image_url": f"data:image/png;base64,{b64}",
                        # opcional: "detail": "low" | "high" | "auto"
                    },
                ],
            }
        ],
    )

    return resp.output_text
