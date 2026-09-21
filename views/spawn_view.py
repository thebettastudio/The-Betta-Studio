# Side-by-side Breeder Cards
                    col_male, col_female = st.columns(2)

                    # --- Male Breeder Image & Details ---
                    with col_male:
                        st.markdown("#### ♂️ Male Breeder")
                        male_img_src = (
                            male.get("photo_id") or 
                            male.get("image_url") or 
                            male.get("image") or 
                            male.get("photo") or 
                            ""
                        )
                        
                        # Split male card into Image (1/4) and Info (3/4)
                        m_img_col, m_info_col = st.columns([1, 3])
                        
                        with m_img_col:
                            display_breeder_image(male_img_src, gender_label="Male")
                            
                        with m_info_col:
                            st.markdown(f"**ID:** `{male.get('id', spawn['male_id'])}`")
                            st.markdown(f"**Variety:** {male.get('variety', 'N/A')}")
                            st.markdown(f"**Grade:** `{male.get('grade', 'N/A')}`")

                    # --- Female Breeder Image & Details ---
                    with col_female:
                        st.markdown("#### ♀️ Female Breeder")
                        female_img_src = (
                            female.get("photo_id") or 
                            female.get("image_url") or 
                            female.get("image") or 
                            female.get("photo") or 
                            ""
                        )
                        
                        # Split female card into Image (1/4) and Info (3/4)
                        f_img_col, f_info_col = st.columns([1, 3])
                        
                        with f_img_col:
                            display_breeder_image(female_img_src, gender_label="Female")
                            
                        with f_info_col:
                            st.markdown(f"**ID:** `{female.get('id', spawn['female_id'])}`")
                            st.markdown(f"**Variety:** {female.get('variety', 'N/A')}")
                            st.markdown(f"**Grade:** `{female.get('grade', 'N/A')}`")
