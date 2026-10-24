"""Transactional package export regression tests using only temporary files."""
import os
import pytest
import merge_fonts as mf


def config(tmp_path, overwrite=True):
    source = tmp_path / 'input.ttf'
    source.write_bytes(b'not-a-font')
    target = tmp_path / 'Output'
    target.mkdir()
    (target / 'keep.txt').write_text('previous export')
    return {'baseFont': {'path': str(source)}, 'output': {'familyName': 'Test'},
            'export': {'package': {'dir': str(target), 'overwrite': overwrite}}}


def fake_build(cfg):
    target = cfg['export']['package']['dir']
    os.mkdir(target)
    font = os.path.join(target, 'Output.ttf')
    with open(font, 'w') as f:
        f.write('new export')
    return {'outputDir': target, 'fontPath': font, 'configPath': None, 'files': [font]}


def test_invalid_font_preserves_old_export(tmp_path):
    cfg = config(tmp_path)
    with pytest.raises(Exception):
        mf.package_fonts(cfg)
    assert (tmp_path / 'Output/keep.txt').read_text() == 'previous export'


@pytest.mark.parametrize('error', [OSError('disk full'), KeyboardInterrupt()])
def test_build_failure_or_cancel_preserves_old_export(tmp_path, monkeypatch, error):
    cfg = config(tmp_path)
    def fail(_):
        raise error
    monkeypatch.setattr(mf, '_build_font_package', fail)
    with pytest.raises(type(error)):
        mf.package_fonts(cfg)
    assert (tmp_path / 'Output/keep.txt').read_text() == 'previous export'


def test_success_returns_final_paths(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(mf, '_build_font_package', fake_build)
    result = mf.package_fonts(cfg)
    assert result['fontPath'] == str(tmp_path / 'Output/Output.ttf')
    assert result['files'] == [result['fontPath']]
    assert (tmp_path / 'Output/Output.ttf').read_text() == 'new export'
    assert not (tmp_path / 'Output/keep.txt').exists()


def test_replace_failure_rolls_back(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(mf, '_build_font_package', fake_build)
    rename = os.rename
    def fail_install(src, dst):
        if os.path.basename(src) == 'Output' and '.font-baker-export-' in src:
            raise OSError('replacement failed')
        rename(src, dst)
    monkeypatch.setattr(mf.os, 'rename', fail_install)
    with pytest.raises(OSError):
        mf.package_fonts(cfg)
    assert (tmp_path / 'Output/keep.txt').read_text() == 'previous export'


def test_input_inside_output_rejected(tmp_path):
    cfg = config(tmp_path)
    cfg['baseFont']['path'] = str(tmp_path / 'Output/keep.txt')
    with pytest.raises(ValueError, match='contain an input'):
        mf.package_fonts(cfg)
    assert (tmp_path / 'Output/keep.txt').exists()


def test_symlink_output_rejected(tmp_path):
    cfg = config(tmp_path)
    (tmp_path / 'link').symlink_to(tmp_path / 'Output', target_is_directory=True)
    cfg['export']['package']['dir'] = str(tmp_path / 'link')
    with pytest.raises(ValueError, match='symbolic link'):
        mf.package_fonts(cfg)
    assert (tmp_path / 'Output/keep.txt').exists()


def test_target_appearing_during_generation_is_preserved(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    target = tmp_path / 'NewOutput'
    cfg['export']['package']['dir'] = str(target)
    def build(cfg):
        result = fake_build(cfg)
        target.mkdir()
        (target / 'keep.txt').write_text('other process')
        return result
    monkeypatch.setattr(mf, '_build_font_package', build)
    with pytest.raises(RuntimeError, match='changed during export'):
        mf.package_fonts(cfg)
    assert (target / 'keep.txt').read_text() == 'other process'
