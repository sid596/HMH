"""One recording per turn, explicit error recovery, no calls caused by UI reruns."""
import hashlib
import io
import wave
from engine.provider_errors import ModelRequestError
from engine.core import Session, understanding_score
from engine.localization import localized_pack


def validate_recording(audio):
    with wave.open(io.BytesIO(audio), "rb") as recording:
        duration = recording.getnframes() / recording.getframerate()
    if not 0 < duration <= 30:
        raise ValueError("Record an answer between 0 and 30 seconds")


class Conversation:
    def __init__(self, pack, directory, stt_language="hi-IN", tts_language="hi-IN", voice="Nalini", include_disclosure=True, message_overrides=None):
        if pack.get("language") and pack["language"] != tts_language:
            raise ValueError("Speaking language must match rubric language")
        self.include_disclosure=include_disclosure
        self.message_overrides=message_overrides or {}
        self.session = Session(pack, directory, "live")
        self.session.audit.append("voice_configuration", speaking_language=tts_language,
                                  listening_language=stt_language, voice=voice, model="timbre-v2.5")
        self.stt_language, self.tts_language, self.voice = stt_language, tts_language, voice
        self.completed = set()
        self.transcripts = {}
        self.failed = set()
        self.speeches = {}
        self.speech_errors = set()
        self.history = []
        self.feedback = ""
        self.error = None

    @property
    def turn(self):
        s = self.session
        return f"localized-feedback-2:{s.index}:{s.attempt}:{s.status}"

    def messages(self):
        # Older session snapshots may predate translated messages. Resolve those
        # from the selected output language, never from the detected input language.
        if self.session.pack.get("language") not in (None, self.tts_language):
            raise ValueError("Speaking language must match rubric language")
        return {**(self.session.pack.get("messages") or localized_pack(self.tts_language)["messages"]), **self.message_overrides}

    def speech_text(self):
        s = self.session
        if s.status == "human_review":
            return self.messages()["human_review"]
        if s.status != "active":
            return self.messages()["complete"]
        c = s.clause
        explanation = c["fallback_explain"] if s.attempt >= 2 else c["explain"]
        disclosure = s.pack["disclosure"] if self.include_disclosure and s.index == 0 and s.attempt == 0 else ""
        # Derive the acknowledgement from the verdict on every turn. Do not reuse
        # a cached feedback string that may come from an older language/session.
        feedback = self.messages()[self.history[-1]["verdict"]] if self.history else ""
        return " ".join(x for x in [disclosure, feedback, explanation, c["question"]] if x)

    def speak(self, synthesizer, retry=False):
        turn = self.turn
        if turn in self.speeches:
            return self.speeches[turn]
        if turn in self.speech_errors and not retry:
            return None
        try:
            audio = synthesizer(self.speech_text(), language=self.tts_language, voice=self.voice)
            self.speeches[turn] = audio
            self.speech_errors.discard(turn)
            self.session.audit.append("tts_generated", turn=turn, text=self.speech_text(),
                                      language=self.tts_language, voice=self.voice)
            return audio
        except Exception as exc:
            self.speech_errors.add(turn)
            self.session.audit.append("tts_failed", turn=turn, error_type=type(exc).__name__)
            return None

    def receive(self, audio, transcriber, scorer, retry=False):
        if self.session.status != "active":
            return False
        token = (self.turn, hashlib.sha256(audio).hexdigest())
        if token in self.completed or (token in self.failed and not retry):
            return False
        stage = "recording"
        try:
            validate_recording(audio)
            stage = "transcription"
            if token not in self.transcripts:
                result = transcriber(audio, language=self.stt_language)
                answer = result["transcript"].strip()
                if not answer:
                    raise ValueError("No speech recognized")
                self.transcripts[token] = result
                self.session.audit.append("transcription", clause_id=self.session.clause["id"],
                                          transcript=answer, metadata={k:v for k,v in result.items() if k != "transcript"})
            result = self.transcripts[token]
            answer = result["transcript"].strip()
            stage = "assessment"
            evidence = scorer(answer, self.session.clause)
            action = self.session.submit(answer, evidence, source="prisma",
                transcript_metadata={k:v for k,v in result.items() if k != "transcript"})
            self.completed.add(token)
            self.failed.discard(token)
            self.error = None
            self.history.append({"answer": answer, "verdict": "understood" if action == "pass" else evidence.verdict, "rubric_verdict":evidence.verdict, "understanding_score":understanding_score(evidence), "action": action})
            return True
        except Exception as exc:
            self.failed.add(token)
            self.error = {"stage": stage, "type": type(exc).__name__}
            if isinstance(exc, ModelRequestError):
                self.error["message"] = str(exc)
            self.session.audit.append("voice_turn_failed", stage=stage, error_type=type(exc).__name__)
            return False

    def receive_transcript(self, answer, scorer, metadata=None):
        """Assess a provider transcript without fabricating an audio recording."""
        if self.session.status != "active":
            return False
        answer = answer.strip()
        if not answer or len(answer) > 12000:
            raise ValueError("No usable speech transcript")
        evidence = scorer(answer, self.session.clause)
        action = self.session.submit(answer, evidence, source="twilio_gather", transcript_metadata=metadata or {})
        self.session.audit.append("transcription", transcript=answer, metadata=metadata or {}, provider="twilio_gather")
        self.history.append({"answer": answer, "verdict": "understood" if action == "pass" else evidence.verdict, "rubric_verdict":evidence.verdict, "understanding_score":understanding_score(evidence), "action": action})
        return True
