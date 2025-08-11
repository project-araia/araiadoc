import pymupdf
import layoutparser as lp
import sys
import numpy as np
import os
from tqdm import tqdm

my_dpi = 150

def scrape_images(input_file, last_pg, output_dir):
    doc = pymupdf.open(input_file)
    # pdf_base = os.path.splitext(os.path.basename(sys.argv[1]))[0]

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)  # Create the directory if it doesn't exist

    model = lp.models.Detectron2LayoutModel(
        config_path='lp://PubLayNet/faster_rcnn_R_50_FPN_3x/config',
        extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.5],
        label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"}
    )

    image_paths = []
    image_ct    = 0

    print(f"  Skipping pages beyond {last_pg} (zero-based indexing).")

    for page_num, page in tqdm(enumerate(doc), total=len(doc), desc="Scraping images", position=0):
        if page_num > last_pg:
            continue

        pix = page.get_pixmap(dpi=my_dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        layout = model.detect(img)

        for block_num, block in enumerate(layout):
            img_index = 0
            scale = 72/my_dpi # convert from pixel space to PDF point space (1/72in)

            x1, y1, x2, y2 = block.coordinates
            x1, x2 = sorted([x1*scale, x2*scale])
            y1, y2 = sorted([y1*scale, y2*scale])


            x_sz = x2-x1
            y_sz = y2-y1

            if block.type != 'Figure':
                continue

            print(f"  block: page = {page_num+1}, score = {block.score:.2f}, type = {block.type}, size = {x_sz:.2f}x{y_sz:.2f}")

            if block.score < 0.7:
                print("    Skipping: low score")
                continue

            if not all(map(np.isfinite, [x1,y1,x2,y2])):
                print("    Skipping: invalid coordinates")
                continue

            # if x_sz < 150 or y_sz < 150:
            if x_sz < 150 or y_sz < 100:
                print("    Skipping: too small")
                continue

            if x_sz < 1.25*y_sz:
                print("    Skipping: too tall")
                continue

            clip_rect = pymupdf.Rect(x1, y1, x2, y2)
            #print(f"    clip x1={x1:.2f} x2={x2:.2f} y1={y1:.2f} y2={y2:.2f} width={clip_rect.width:.2f} height={clip_rect.height:.2f}")

            new_pdf = pymupdf.open()
            single_page = new_pdf.new_page(width=clip_rect.width, height=clip_rect.height)
            single_page.show_pdf_page(
                pymupdf.Rect(0, 0, clip_rect.width, clip_rect.height),
                doc,
                page.number,
                clip=clip_rect
            )

            # pdf_path = f"{pdf_base}_page{page_num+1}_figure{block_num+1}.pdf"
            image_filename = f"page{page_num}_img{img_index+1}.pdf"
            image_path = os.path.join(output_dir, image_filename)
            new_pdf.save(image_path)
            new_pdf.close()

            img_index += 1
            image_ct  += 1
            #print(f"    adding {image_path}")
            image_paths.append(image_path)

    print(f"  Found {image_ct} plausible images in paper body: {image_paths}.")

    return image_paths


