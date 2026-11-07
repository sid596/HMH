"""One recording per turn, explicit error recovery, no calls caused by UI reruns."""
import hashlib
import io
import wave
from engine.core import Session


def validate_recording(audio):
    with wave.open(io.BytesIO(audio), "rb") as recording:
        duration = recording.getnframes() / recording.getframerate()
    if not 0 < duration <= 30:
        raise ValueError("Record an answer between 0 and 30 seconds")


class Conversation:
    def __init__(self, pack, directory, stt_language="hi-IN", tts_language="hi-IN", voice="Nalini"):
        self.session = Session(pack, directory, "live")
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
        return f"{s.index}:{s.attempt}:{s.status}"

    def speech_text(self):
        s = self.session
        if s.status == "human_review":
            return "Main yeh verification yahin rok rahi hoon. A team member needs to review this with you. Consent accept nahi hua hai."
        if s.status != "active":
            return "Thank you. Aapne saare demo teach-back checks complete kar liye hain. Yeh fictional demo hai, legal consent certificate nahi."
        c = s.clause
        explanation = c["fallback_explain"] if s.attempt >= 2 else c["explain"]
        disclosure = s.pack["disclosure"] if s.index == 0 and s.attempt == 0 else ""
        return " ".join(x for x in [disclosure, self.feedback, explanation, c["question"]] if x)

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
            self.history.append({"answer": answer, "verdict": evidence.verdict, "action": action})
            self.feedback = {
                "understood": "Thank you, aapne yeh point explain kar diya. Ab agla point.",
                "partial": "Aapne kuch points explain kiye. Main baaki baat phir se clear karti hoon.",
                "misunderstood": "Shayad meri explanation clear nahi thi. Main terms phir se explain karti hoon.",
                "no_evidence": "Sirf haan se mujhe understanding check karne mein madad nahi milti. Please apne words mein batayein."
            }[evidence.verdict]
            return True
        except Exception as exc:
            self.failed.add(token)
            self.error = {"stage": stage, "type": type(exc).__name__}
            self.session.audit.append("voice_turn_failed", stage=stage, error_type=type(exc).__name__)
            return False
