"""Tests for Brazilian PII detection — CPF, CNPJ, RG, PIX, CEP."""

from aion.estixe.guardrails import Guardrails


class TestPIIBrasil:

    def setup_method(self):
        self.g = Guardrails()

    # ── CPF ──

    def test_cpf_formatted(self):
        result = self.g.check_output("Meu CPF é 123.456.789-09")
        assert not result.safe
        assert any("cpf" in v for v in result.violations)
        assert "CPF_REDACTED" in result.filtered_content

    def test_cpf_unformatted(self):
        result = self.g.check_output("CPF: 12345678909")
        assert not result.safe
        assert any("cpf" in v for v in result.violations)

    # ── CNPJ ──

    def test_cnpj_formatted(self):
        result = self.g.check_output("CNPJ: 12.345.678/0001-95")
        assert not result.safe
        assert any("cnpj" in v for v in result.violations)
        assert "CNPJ_REDACTED" in result.filtered_content

    def test_cnpj_unformatted(self):
        result = self.g.check_output("CNPJ 12345678000195")
        assert not result.safe
        assert any("cnpj" in v for v in result.violations)

    # ── Email ──

    def test_email(self):
        result = self.g.check_output("Mande para joao@empresa.com.br")
        assert not result.safe
        assert any("email" in v for v in result.violations)

    # ── Phone ──

    def test_phone_br(self):
        result = self.g.check_output("Ligue para +5511999887766")
        assert not result.safe

    # ── PIX ──

    def test_pix_uuid(self):
        result = self.g.check_output("Chave PIX: 123e4567-e89b-12d3-a456-426614174000")
        assert not result.safe
        assert any("pix" in v for v in result.violations)

    def test_pix_phone(self):
        result = self.g.check_output("PIX: +5511999887766")
        assert not result.safe

    # ── CEP ──

    def test_cep(self):
        result = self.g.check_output("CEP: 01310-100")
        assert not result.safe
        assert any("cep" in v for v in result.violations)

    # ── API Keys ──

    def test_api_key(self):
        result = self.g.check_output("Use a key sk-proj-abc123def456ghi789jkl012mno")
        assert not result.safe
        assert any("api_key" in v for v in result.violations)

    def test_aws_key(self):
        result = self.g.check_output("AWS key: AKIAIOSFODNN7EXAMPLE")
        assert not result.safe
        assert any("aws_key" in v for v in result.violations)

    # ── Clean content ──

    def test_safe_content(self):
        result = self.g.check_output("A capital do Brasil é Brasília.")
        assert result.safe
        assert not result.violations

    def test_safe_numbers(self):
        result = self.g.check_output("O resultado foi 42.")
        assert result.safe
