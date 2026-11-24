from shopagent.emotion import EmotionDetector


def test_high_risk_complaint_handoff():
    detector = EmotionDetector()
    result = detector.analyze("你们这什么垃圾服务，我要投诉到12315！")
    assert result.level >= 2
    assert result.should_handoff is True
    assert "投诉" in result.matched or "12315" in result.matched


def test_normal_refund_not_handoff():
    result = EmotionDetector().analyze("我要退款")
    assert result.should_handoff is False


def test_negated_complaint_not_handoff():
    result = EmotionDetector().analyze("我不是投诉，只是想问物流到哪了")
    assert result.should_handoff is False


def test_repeated_frustration_escalates():
    text = "等了好几天还没发货，很失望"
    low = EmotionDetector().analyze(text, negative_turns=0)
    high = EmotionDetector().analyze(text, negative_turns=2)
    assert high.score > low.score
    assert high.should_handoff is True


def test_positive_tone_stays_calm():
    result = EmotionDetector().analyze("谢谢，挺好用的")
    assert result.level == 0
