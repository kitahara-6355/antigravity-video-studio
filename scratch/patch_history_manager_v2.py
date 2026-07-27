def main():
    file_path = "backend/branding/history_manager.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    is_crlf = "\r\n" in content
    content_lf = content.replace("\r\n", "\n")

    # NumPyなしフォールバック版の置換 (正確なターゲット)
    target_fallback = """            except ImportError:
                import random
                # NumPyがない場合のフォールバック: 1024x1024のサイズで高精細なグラデーションを作成し、LANCZOSで拡大して画質を最大化
                grad_size = 1024
                grad_line = Image.new("RGB", (grad_size, 1))
                half_size = grad_size // 2
                for x in range(half_size):
                    t = x / (half_size - 1)
                    r = int(color1[0] * (1 - t) + color2[0] * t)
                    g = int(color1[1] * (1 - t) + color2[1] * t)
                    b = int(color1[2] * (1 - t) + color2[2] * t)
                    grad_line.putpixel((x, 0), (r, g, b))
                for x in range(half_size):
                    t = x / (half_size - 1)
                    r = int(color2[0] * (1 - t) + color3[0] * t)
                    g = int(color2[1] * (1 - t) + color3[1] * t)
                    b = int(color2[2] * (1 - t) + color3[2] * t)
                    grad_line.putpixel((half_size + x, 0), (r, g, b))
                
                grad_2d = Image.new("RGB", (grad_size, grad_size))
                for y in range(grad_size):
                    for x in range(grad_size):
                        idx = int((x + y) / (2 * grad_size - 2) * (grad_size - 1))
                        r, g, b = grad_line.getpixel((idx, 0))
                        dither = random.randint(-1, 1)
                        rn = min(255, max(0, r + dither))
                        gn = min(255, max(0, g + dither))
                        bn = min(255, max(0, b + dither))
                        grad_2d.putpixel((x, y), (rn, gn, bn))
                img = grad_2d.resize((w_draw, h_draw), Image.Resampling.LANCZOS)"""

    replacement_fallback = """            except ImportError:
                import random
                # NumPyがない場合のフォールバック: Smoothstepによる滑らかなグラデーション
                grad_size = 1024
                grad_line = Image.new("RGB", (grad_size, 1))
                half_size = grad_size // 2
                for x in range(half_size):
                    t = x / (half_size - 1)
                    t_smooth = t * t * (3.0 - 2.0 * t)
                    r = int(color1[0] * (1 - t_smooth) + color2[0] * t_smooth)
                    g = int(color1[1] * (1 - t_smooth) + color2[1] * t_smooth)
                    b = int(color1[2] * (1 - t_smooth) + color2[2] * t_smooth)
                    grad_line.putpixel((x, 0), (r, g, b))
                for x in range(half_size):
                    t = x / (half_size - 1)
                    t_smooth = t * t * (3.0 - 2.0 * t)
                    r = int(color2[0] * (1 - t_smooth) + color3[0] * t_smooth)
                    g = int(color2[1] * (1 - t_smooth) + color3[1] * t_smooth)
                    b = int(color2[2] * (1 - t_smooth) + color3[2] * t_smooth)
                    grad_line.putpixel((half_size + x, 0), (r, g, b))
                
                grad_2d = Image.new("RGB", (grad_size, grad_size))
                for y in range(grad_size):
                    for x in range(grad_size):
                        factor = (x + y) / (2 * grad_size - 2)
                        idx = int(factor * (grad_size - 1))
                        r, g, b = grad_line.getpixel((idx, 0))
                        dither = random.uniform(-0.8, 0.8)
                        rn = min(255, max(0, int(r + dither)))
                        gn = min(255, max(0, int(g + dither)))
                        bn = min(255, max(0, int(b + dither)))
                        grad_2d.putpixel((x, y), (rn, gn, bn))
                img = grad_2d.resize((w_draw, h_draw), Image.Resampling.LANCZOS)"""

    target_fallback_lf = target_fallback.replace("\r\n", "\n")
    replacement_fallback_lf = replacement_fallback.replace("\r\n", "\n")

    if target_fallback_lf in content_lf:
        content_lf = content_lf.replace(target_fallback_lf, replacement_fallback_lf)
        print("Replaced: Fallback gradient")
    else:
        print("Warning: target_fallback_lf not found")

    if is_crlf:
        final_content = content_lf.replace("\n", "\r\n")
    else:
        final_content = content_lf

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(final_content)

if __name__ == '__main__':
    main()
